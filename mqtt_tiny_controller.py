import network,urequests, time, ubinascii
import random, json, re, gc, os, machine
import uasyncio as asyncio
from mqtt_as import MQTTClient, config
from mqtt_tiny_controller_config import *
from mqtt_local import get_temperature, toggle_onboard_led, set_onboard_led
from machine import Pin
from collections import OrderedDict

#
# Description: 
# MqttTinyController runs on Raspberry Pi PicoW (RP2040) using any free cloud MQTT broker (e.g. HiveHQ or Mosquitto) to control home automation relay switches and contact switches.
#
# For installation and examples, please read the project readme on GitHub:
# Github: https://github.com/DIY-able/MqttTinyController

# mqtt_as.py and mqtt_local.py are written by Peter Hinch. It's an AMAZING library. Forget about umqtt.simple, umqtt.robust!
# Github: https://github.com/peterhinch/micropython-mqtt 

# Change Log:
# Mar 17, 2023, v1.0   [DIYable] - Based on umqtt sample, fixed memory errors and implementing automatic reconnection logic for both WiFi and MQTT broker.
# Jan 30, 2024, v1.1   [DIYable] - Integrated JSON payload support to accommodate the mobile app "IoT MQTT Panel."
# Feb 01, 2024, v1.2   [DIYable] - Added hardware burnout protection (for relays PIN.OUT only) 
# Feb 03, 2024, v1.3   [DIYable] - Introduced momentary switch feature for relays (beneficial for garage opener remote control)
# Feb 04, 2024, v1.4   [DIYable] - Refactored code to use class MqttPublishStats and class MqttGpioHardware
# Feb 06, 2024, v1.5   [DIYable] - Incorporated an onboard LED for status indication.
# Feb 08, 2024, v1.6   [DIYable] - Refactored code formatting from camelCase and PascalCase to snake_case following PEP (Python Enhancement Proposal) guidelines.
# Feb 09, 2024, v1.7   [DIYable] - Resolved a bug related to log publishing errors to the MQTT broker during reconnection scenarios.
# Feb 12, 2024, v1.8   [DIYable] - Addressed the issue where complete WiFi disconnection would cause hangs on QoS1, though unable to resolve, mitigated by switching to QoS0 in such cases.
# Feb 13, 2024, v1.9   [DIYable] - Rewrote code using mqtt_as (Thanks to Peter Hinch's amazing work on mqtt_as!) and uasyncio lib to solve problem of QoS1 socket hangs issue when WIFI is down.
# Feb 17, 2024, v2.0   [DIYable] - Optimized JSON publishing by only transmitting changed GPIO values, except during initial runs or reconnections after QoS1 outages to prevent old values from overriding new ones.
# Feb 18, 2024, v2.0.1 [DIYable] - Implemented a retry loop before invoking "mqtt_as" code to address situations where weak WiFi signal or power outages lead to premature quitting.
# Feb 19, 2024, v2.0.2 [DIYable] - Included total uptime statistics, outage count and onboard tempeature in the published data. 
# Feb 20, 2024, v2.0.3 [DIYable] - Added commands "stats", "refresh", "getip" and Implemented flashing LED for powering up and machine.reset for permanent failure.
# Feb 21, 2024, v2.0.4 [DIYable] - Added async flashing status for onboard LED before fully connected. Removed blue_led() from code and added toggle_onboard_led, set_onboard_led to mqtt_local

# References:
# https://github.com/micropython/micropython-lib/tree/master/micropython/umqtt.simple (very simple)
# https://peppe8o.com/mqtt-and-raspberry-pi-pico-w-start-with-mosquitto-micropython/  (machine.reset? really!)
# https://www.hivemq.com/blog/iot-reading-sensor-data-raspberry-pi-pico-w-micropython-mqtt-node-red/
# https://www.tomshardware.com/how-to/send-and-receive-data-raspberry-pi-pico-w-mqtt
# https://mpython.readthedocs.io/en/master/library/mPython/umqtt.simple.html
# https://github.com/micropython/micropython-lib/issues/103 (Qos1 sock WiFi is degraded)
# https://github.com/micropython/micropython/issues/2568 (Mqtt Wifi dropped, timeout)
# https://github.com/peterhinch/micropython-mqtt (Peter Hinch's "mqtt_as", the resilient asynchronous MQTT driver. Recovers from WiFi and broker outages)

#  ----------------------------------------------------------------------------

# Update status (dictionary in memory) from GPIO hardware value
# e.g. method("GP15")
def update_gpio_status_from_hardware(name):    
    value = get_gpio_value_from_hardware(name)
    if (value != -1):
        mqtt_gpio_hardware[name].status  = value
        
# Get the status from dictionary in memory 
def get_current_gpio_value(name):
    try:         
        return mqtt_gpio_hardware[name].status
    except KeyError as ke:
         pass   

# Get GPIO value from hardware
# e.g. method("GP15") returns 1 or 0 (int)
def get_gpio_value_from_hardware(name):
    value = -1
    if (mqtt_gpio_hardware[name].pin.value() is not None):
        value = flip_value(mqtt_gpio_hardware[name].pin.value())            
    return value

# Convert Name(string) to Pin(int)
# e.g. method("GP15") returns 15
def get_gp_name_to_pin(name):
    start = name.find(gpio_prefix)+len(gpio_prefix)
    end = len(name)
    return int(name[start:end])


# Set GPIO value on hardware
# e.g. method("GP15", 1) 
def set_gpio_value_on_hardware(name, value):
    
    # This is more to set GPIO on/off for Relay
    # value = 0, 0V on output -> the breakout board GPIO(x) LED and relay(x) LED will be off, Relay(x) = ON
    # value = 1, 3.3V on output -> the breakout board GPIO(x) LED and relay(x) LED will be on, Relay(x) = OFF
    
    is_gpio_set = True
    message = ""
    global mqtt_publish_stats
        
    try:
        # Business logic to determine if hardware gpio should be set or not
        if ((time.time() - mqtt_gpio_hardware[name].last_modified_time) < hardware_modified_cooldown_period_in_seconds):
            is_gpio_set = False
            message = "Warning: Skipping Gpio {} value change for hardware burnout protection, min interval between value change is {} seconds".format(name, hardware_modified_cooldown_period_in_seconds)
            log(message)
            mqtt_publish_stats.is_republish = True   # Since we are ignoring the changes, client needs to be updated by republish
            
        if (((time.time() - mqtt_gpio_hardware[name].last_modified_time) < hardware_modified_threshold_in_seconds) and mqtt_gpio_hardware[name].modified_counter > hardware_modified_max):
            is_gpio_set = False
            mqtt_gpio_hardware[name].violation_counter = mqtt_gpio_hardware[name].violation_counter + 1    # Store total number of violation will lead to permanent fail
            message = "Warning: Skipping Gpio {} value change for hardware burnout protection, number of change exceeded max threshold {} in {} seconds".format(name, hardware_modified_max, hardware_modified_threshold_in_seconds)
            log(message)
            mqtt_publish_stats.is_republish = True   # Since we are ignoring the changes, client needs to be updated by republish
        elif (((time.time() - mqtt_gpio_hardware[name].last_modified_time) > hardware_modified_threshold_in_seconds) and mqtt_gpio_hardware[name].modified_counter > 0):
            mqtt_gpio_hardware[name].modified_counter = 0
            
        if (mqtt_gpio_hardware[name].violation_counter > hardware_violation_max + 1):
            message = "Error: Gpio {} value change is permanently disabled (until hardware reset) for protection, number of violation exceeded {}".format(name, hardware_violation_max)
            log(message)
            mqtt_publish_stats.is_republish = True   # Since we are ignoring the changes, client needs to be updated by republish
            mqtt_gpio_hardware[name].is_modified_allowed = False
            
        if (is_gpio_set == True):
            if (mqtt_gpio_hardware[name].is_modified_allowed == True):
                if (mqtt_gpio_hardware[name].is_momentary == True):
                    Pin(get_gp_name_to_pin(name), mode=Pin.OUT, value=0)  # On (0)
                    time.sleep(momentary_switch_delay_in_seconds)
                    Pin(get_gp_name_to_pin(name), mode=Pin.OUT, value=1)  # Off (1)    
                    mqtt_gpio_hardware[name].is_changed = True  #  Publish this GPIO (hardware detection won't work because PIN returns to the original state)
                else: 
                    Pin(get_gp_name_to_pin(name), mode=Pin.OUT, value=flip_value(value)) # Regular relay switch
                    
                mqtt_gpio_hardware[name].last_modified_time = time.time()
                mqtt_gpio_hardware[name].modified_counter = mqtt_gpio_hardware[name].modified_counter + 1          
    except KeyError as ke:
         pass
    
                
# Flip 0 to 1 and 1 to 0 because of Pin.PULL_UP (for both contacts and relays), disconnected = 1 and connected = 0
# We need to flip it reverse to connected = 1 and disconnected = 0 (more human readable)
# e.g method(0) returns 1
def flip_value(value):
     if (value == 1):
        return 0
     if (value == 0):
        return 1
               
# Check if the hardware GPIO value are different from in memory GPIO in dictionary
def is_gpio_values_changed():    
    is_changed = False
    
    merged_list = gpio_pins_for_relay_switch.copy()
    merged_list.update(gpio_pins_for_momentary_relay_switch)    
    merged_list.update(gpio_pins_for_contact_switch)
       
    # Publish if memory value is different from the hardware GPIO value
    for x in merged_list:
        name = gpio_prefix+str(x)
        if (get_current_gpio_value(name) != get_gpio_value_from_hardware(name)):            
            update_gpio_status_from_hardware(name)
            mqtt_gpio_hardware[name].is_changed = True
            is_changed = True
            print ("GPIO hardware value is changed")
        elif (mqtt_gpio_hardware[name].is_changed == True):   # Special case: when momentary switch is toogled, hardware status returns to original state but it has been touched
            is_changed = True
            print ("GPIO value was changed (momentary switch)")
            
    return is_changed
  
# Check if GPIO status should be published to MQTT broker   
def is_publish_gpio_status():

    is_publish = False
    is_full = False
    is_changed = is_gpio_values_changed()   # Check if any GPIO hardware value has changed compare to master copy in dictionary
    
    # Business logic safeguard to disable publishing in case of error
    if (((time.time() - mqtt_publish_stats.last_published_time) < publish_threshold_in_seconds) and (mqtt_publish_stats.publish_counter > publish_counter_max)):
        # To test this case, set is_changed = True in is_gpio_values_changed() to flood the broker
        mqtt_publish_stats.publish_counter = -1
        log("Error: Abnormal number of publish detected in a short interval, publishing is stopped until hardware restart")                   
    elif  (((time.time() - mqtt_publish_stats.last_published_time) > publish_threshold_in_seconds) and mqtt_publish_stats.publish_counter >=0):
        mqtt_publish_stats.publish_counter = 0  
           
    # Publish full list status to Mqtt broker first time running or republish, otherwise only send the changed values
    if (mqtt_publish_stats.is_first_time_run == True):   
        mqtt_publish_stats.is_first_time_run = False
        log(f"Subscribed for ClientID: {mqtt_client_id.decode('utf-8')}")
        print("Publish (First time), send full list")
        is_publish = True
        is_full = True
    elif (mqtt_publish_stats.is_republish == True):                
        mqtt_publish_stats.is_republish = False
        print("Publish (Republish), send full list")
        is_publish = True
        is_full = True
    elif (((time.time() - mqtt_publish_stats.last_scheduled_published_time) > scheduled_publish_in_seconds) and scheduled_publish_in_seconds > 0):
        mqtt_publish_stats.last_scheduled_published_time = time.time()    # If last_scheduled_published_time exceeded defined time, then publish
        print("Publish (Scheduled), send full list")
        is_publish = True        
        is_full = True
    elif (is_changed == True and mqtt_publish_stats.publish_counter >= 0): # If publish_counter == -1 (error), it will skip publishing forever until hardware reset
        print("Publish (Changed), only send changed values")
        is_publish = True
        is_full = False  # Only publish changed values
        
    return is_publish, is_full


# Get all GPIO status from the master dictionary for JSON publish
def get_gpio_status(full=False):    

    gpioStatus = OrderedDict()
    
    # Get the list in sorted order because of leading 0 integer won't work in string sorted (i.e. GP1, GP16, GP2) 
    merged_list = gpio_pins_for_relay_switch.copy()
    merged_list.update(gpio_pins_for_momentary_relay_switch)    
    merged_list.update(gpio_pins_for_contact_switch)

    # Get the list of integer (ToDo: refactor needed - maybe there is a better way to do this in Python)
    temp_list = []
    for a in merged_list:
        temp_list.append(a)

    # Sort the integer and then combined into OrderedDict, regular dictionary won't sort properly with JSON.dumps()
    for x in sorted(temp_list):        
        name = gpio_prefix+str(x)
        if (full == False):
            if (mqtt_gpio_hardware[name].is_changed == True):
                gpioStatus[name] = mqtt_gpio_hardware[name].status
                mqtt_gpio_hardware[name].is_changed = False
        else:
            gpioStatus[name] = mqtt_gpio_hardware[name].status
        
    return gpioStatus       
          
# Log message printing it and also send to MQTT broker           
def log(message):
    print(message)
    global mqtt_publish_stats
    mqtt_publish_stats.log_messages.append(message)  # Save the message until next iteration in the loop to publish. If we call mqtt client here, race condition error
        

#  ----------------------------------------------------------------------------          
    
# Get the stats such as uptime and outages
def get_stats():
    total_uptime = (time.time() - mqtt_publish_stats.startup_time)
    uptime_days, uptime_hours, uptime_minutes, uptime_seconds = calculate_time(total_uptime)
    return (f"Uptime={uptime_days} days {uptime_hours} hrs, Outages={mqtt_publish_stats.outage_counter}, Mem={get_memory_usage()}, Temp={get_temperature()}")
    
# Print memory usage                
def print_memory_usage():
    print(f"Memory usage: {get_memory_usage()}")
    
# Get memory usage to check memory leak 
def get_memory_usage(full=False):
  gc.collect()
  F = gc.mem_free()
  A = gc.mem_alloc()
  T = F+A
  P = '{0:.2f}%'.format(A/T*100)
  if not full: return P
  else : return ('Total:{0} Free:{1} ({2})'.format(T,F,P))
  
# Calculate days, hrs, min, sec without using any library 
def calculate_time(seconds):    
    days = seconds // (24 * 3600)  # Calculate days
    seconds %= (24 * 3600)    
    hours = seconds // 3600  # Calculate hours
    seconds %= 3600    
    minutes = seconds // 60  # Calculate minutes    
    seconds %= 60  # Calculate remaining seconds
    return days, hours, minutes, seconds

# Get public ip. Note: this is an async call so it won't block
async def get_public_ip():
    public_ip = None
    try:
        response = urequests.get(json_ip_provider)
        if response.status_code == 200:
            data = response.json()
            public_ip = data.get('ip', None)
        else:
            public_ip = f"Failed to get IP, HTTP code: {response.status_code}"
    except Exception as e:
        public_ip = f"Exception on public IP: {e}"    
    log(public_ip)

#  ----------------------------------------------------------------------------

# Publish Stats class to store all the global stats in mqtt_publish_stats
class PublishStats:    
    last_published_time = 0
    last_scheduled_published_time = 0
    publish_counter = 0
    is_republish = False
    is_first_time_run = False
    startup_time = 0
    log_messages = []
    outage_counter = 0
    is_online = False
    
# Define the property to used in the master dictonary mqtt_gpio_hardware    
class GpioProperty:
    status = 0   # status for all GPIO in 0 or 1  (Note: This is the INVERSE of real pins for human readable purpose, e.g. 0 = Off, 1 = On)
    pin = None   # Instance of real hardware pin object (Note: Low Voltage 0 = On,  High Voltage 1 = Off)
    last_modified_time = 0  # Last modified time for GPIO (only for relays to use only, hardware burnout protection)
    modified_counter = 0   # Modified counter for GPIO (only for relays to use only, hardware burnout protection)
    violation_counter = 0  # Violation counter for GPIO (only for relays to use only, hardware burnout protection)
    is_modified_allowed = False # Is hardware PIN is allowed to set (only for relays, hardware burnout protection)
    is_momentary = False       # Is hardware PIN is defined as momentary (only for relays, e.g. switch it on, it will turn off automatically)
    is_changed = False         # For both contacts and relays to publish only changed GPIO value (no need to publish full list)

#  ----------------------------------------------------------------------------                 

async def pulse(): 
    await asyncio.sleep(1)

# Handling incoming message using event instances and asynchronous iterator, similar to message call back
# To support Android "IoT MQTT Panel", all payload is in JSON
async def messages(client):
    async for topic, msg, retained in client.queue:
        #print(f'Callback Topic: "{topic.decode()}" Message: "{msg.decode()}" Retained: {retained}')        
        message = msg.decode()
        if ((not message.startswith('Subscribed:')) and (not message.startswith('Warning:')) and (not message.startswith('Error:'))):
            print(f"Callback message: {message}")

        is_message_json = False
     
        try:
           json_object = json.loads(message)
           is_message_json = True
        except ValueError as ve:
           is_message_json = False
           
        if (is_message_json == True):
            try:
                for key in json_object:    # Note: key in a dict is unique, e.g. Bad command {"CMD": "getip", "CMD": "stats", "CMD": "republish"} will execute "republish" only
                    if (key == command_prefix):                 
                        # Command in Json received, e.g {"CMD":"getip"}
                        cmd_value = json_object[key]                        
                        if (commands[cmd_value] == 1):  # Use dict as enum without hardcoding
                            log(f"{get_stats()}")
                        elif (commands[cmd_value] == 2):
                            mqtt_publish_stats.is_republish = True
                        elif (commands[cmd_value] == 3):
                            asyncio.create_task(get_public_ip())  # Note: this is an async call
                    else:
                        # GPIO in Json received e.g. {"GP1": 1}
                        value = json_object[key]
                        if (get_current_gpio_value(key) != value):
                            set_gpio_value_on_hardware(key, value)
                            update_gpio_status_from_hardware(key)                            
            except:
                pass
                        
        asyncio.create_task(pulse())
    

async def down(client):
    global mqtt_publish_stats
    while True:
        await client.down.wait()  # Pause until connectivity changes
        client.down.clear()
        mqtt_publish_stats.is_online = False    
        mqtt_publish_stats.outage_counter += 1
        print("WiFi or broker is down.")

async def up(client):
    while True:
        await client.up.wait()
        client.up.clear()
        mqtt_publish_stats.is_online = True
        print(f"Connected for ClientID: {mqtt_client_id.decode('utf-8')}")
        await client.subscribe(mqtt_topic, mqtt_qos)
        
async def onboard_led_online_status():
    while True:
        if (mqtt_publish_stats.is_online == True):
            set_onboard_led(True)
        else:
            toggle_onboard_led()
        await asyncio.sleep(1)
               
#  ----------------------------------------------------------------------------      

# Start up loop for connecting wifi
def startup_connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.config(pm = 0xa11140) # Diable powersave mode
    wlan.connect(wifi_ssid, wifi_pass)

    max_wait = wifi_max_retries
    while max_wait > 0:
        toggle_onboard_led()       # Cannot call asnyc function onboard_led_online_status() before "mqtt_as" starts
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        max_wait -= 1     
        print('Device started: Waiting for connection...')
        time.sleep(1)        
    
    if wlan.status() != 3:
        # raise RuntimeError('Wifi connection permanently Failed')        
        print('Wifi connection permanently Failed, machine will reboot...')
        time.sleep(wifi_reset_delay_in_seconds)        
        machine.reset()
    else:
        print('Wifi Connected')
        print(wlan.ifconfig())
        
    return wlan

#  ----------------------------------------------------------------------------      
# init
def init():
    
    global mqtt_publish_stats
    global mqtt_gpio_hardware    
    global config
    
    # Load configuration for mqtt_as
    config['ssid'] = wifi_ssid
    config['wifi_pw'] = wifi_pass
    config['will'] = (mqtt_topic, f"Disconnected for ClientID={mqtt_client_id.decode('utf-8')}", False, 0) # Last will send as QoS0
    config['keepalive'] = 120
    config["queue_len"] = 1  # Use event interface with default queue
    config['user'] = broker_user
    config['password'] = broker_pass
    config['server'] = broker_server
    config['ssl'] = True   # mqtt_as uses port 8883 if ssl is true or use config['port']
    config['ssl_params'] = {"server_hostname": broker_server}
    config["client_id"] = mqtt_client_id
    config["clean"] = mqtt_clean   # Set this to False (clear session) for reconnection to work Qos1 message recovery during outage
    config["clean_init"] = True   # clean_init should normally be True. If False the system will attempt to restore a prior session on the first connection. This may result in a large backlog of qos==1 messages being received    
    
    mqtt_gpio_hardware = {}
    
    # Combine 2 different relays into one single list
    relay_only_list = gpio_pins_for_relay_switch.copy()
    relay_only_list.update(gpio_pins_for_momentary_relay_switch)   
    
    # Set all Gpio status to 0 and init hardware
    for x in relay_only_list:
        name = gpio_prefix+str(x)        
        mqtt_gpio_hardware[name] = GpioProperty()
        mqtt_gpio_hardware[name].status = 0   # status is using 0 and 1, same as real PIN value
        mqtt_gpio_hardware[name].pin = Pin(x, mode=Pin.OUT, value=1)  # Value=1, high voltage
        mqtt_gpio_hardware[name].last_modified_time = time.time() # only for relay
        mqtt_gpio_hardware[name].modified_counter = 0 # only for relay
        mqtt_gpio_hardware[name].violation_counter = 0 # only for relay
        mqtt_gpio_hardware[name].is_modified_allowed = True # only for relay
        
        if (x in gpio_pins_for_momentary_relay_switch):
            mqtt_gpio_hardware[name].is_momentary = True
        else:
            mqtt_gpio_hardware[name].is_momentary = False
            
        update_gpio_status_from_hardware(name)   # Good practice to sync based on hardware value
        
    # Contact switch
    for y in gpio_pins_for_contact_switch:
        name = gpio_prefix+str(y)
        mqtt_gpio_hardware[name] = GpioProperty()
        mqtt_gpio_hardware[name].status = 0 # status is using 0 and 1, same as real PIN value
        mqtt_gpio_hardware[name].pin = Pin(y, Pin.IN, Pin.PULL_UP)  # Create an input pin, with a pull up resistor
            
        update_gpio_status_from_hardware(name)

        
    # init stats
    mqtt_publish_stats = PublishStats()    
    mqtt_publish_stats.last_published_time = time.time()
    mqtt_publish_stats.last_scheduled_published_time = time.time()
    mqtt_publish_stats.publish_counter = 0    # If it's -1, it errors out and stops publishing forever
    mqtt_publish_stats.is_republish = False
    mqtt_publish_stats.is_first_time_run = True    # First time init to true
    mqtt_publish_stats.startup_time = time.time()
    mqtt_publish_stats.is_online = False   # For onboard LED to use 
            

#  ----------------------------------------------------------------------------      
# main Loop

# Technical notes on wifi/broker test:
#
# Case 1: Auto re-connect when network fails:  
#    Use firewall rules on your router to block traffic to broker after connection is established 
# Case 2: Auto re-connect when Wifi fails (SSID is still available)    
#    Disconnect your PicoW using router admin
# Case 3: Auto re-connect when Wifi totally gone (SSID is NOT available)
#    Power off the router or change the SSID name of WiFi

async def main(client):

    global mqtt_publish_stats
    
    # Create a task to show online status on LED
    asyncio.create_task(onboard_led_online_status())   # Async task for online status
    
    try:        
        await client.connect()
    except OSError:
        print('Connection failed.')
        return
    
    for task in (up, down, messages):
        asyncio.create_task(task(client))


    while True:
        await asyncio.sleep(5)

        # Uncomment this to Delete all RETAIN messages from the MQTT broker (e.g. if you accidentially set the retain flag in "Iot MQTT Panel" app)
        # client.publish(mqtt_topic, '', True)
        
        # Publish log (not updating publish_counter or last_published_time)
        # Notes: If logs are published in callback, it will error out in mqtt broker reconnect scenario. Do this in here. 
        if (mqtt_publish_stats.log_messages is not None):
            for x in mqtt_publish_stats.log_messages:
                await client.publish(mqtt_topic, x, mqtt_retain, mqtt_qos)  #QoS=1, Retain flag=false
                mqtt_publish_stats.log_messages = []                
      
        # Publish full list or partial list to Mqtt broker based on business logic 
        is_publish, is_full = is_publish_gpio_status()
        json_status = None    
        
        if (is_publish and is_full):
             json_status = json.dumps(get_gpio_status(True))   # Get the full list in JSON
        elif (is_publish and not is_full):
             json_status = json.dumps(get_gpio_status(False))  # Get the list of changed values in JSON
             
        # json_status contains either full list of GPIO status values or partial list of changed values
        
        if (is_publish == True):                
            mqtt_publish_stats.publish_counter = mqtt_publish_stats.publish_counter + 1 
            mqtt_publish_stats.last_published_time = time.time()
            await client.publish(mqtt_topic, json_status, mqtt_retain, mqtt_qos)  #QoS=1, Retain flag=false
            

#  ----------------------------------------------------------------------------

mqtt_publish_stats = None
mqtt_gpio_hardware = None
init()

# Note: The "mqtt_as" library operates under the assumption of a stable connection during startup. However, it faces
#       the risk of permanent termination if the WiFi signal is weak during the initial startup or after a reboot following
#       a power outage where the WiFi is not yet available.
# Workaround: To mitigate this issue, a retry loop has been implemented before invoking the "mqtt_as" code.

wlan = startup_connect_wifi()   
if wlan.isconnected():             
    
    # Set up client. Enable optional debug statements.
    MQTTClient.DEBUG = True
    client = MQTTClient(config)

    try:
        print_memory_usage()
        asyncio.run(main(client))
    finally:  # Prevent LmacRxBlk:1 errors.
        print("Shutting down....")
        print_memory_usage()
        set_onboard_led(False)    # PicoW has only one LED 
        client.close()
        asyncio.new_event_loop()



