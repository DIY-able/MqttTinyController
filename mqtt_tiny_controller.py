import network,urequests, time, ubinascii
import random, json, re, gc, os
import uasyncio as asyncio
from mqtt_as import MQTTClient, config
from mqtt_tiny_controller_config import *
from mqtt_local import blue_led 
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
# Mar 17, 2023, v1.0 [DIYable] - Based on umqtt sample, fixed memory error and added auto re-connect wifi/mqtt broker logic
# Jan 30, 2024, v1.1 [DIYable] - Combined publish and subscribe in single file with JSON payload support mobile app "IoT MQTT Panel"
# Feb 01, 2024, v1.2 [DIYable] - Added hardware burnout protection (for relays PIN.OUT only) using timer and counter
# Feb 03, 2024, v1.3 [DIYable] - Added momentary switch for relay (useful for garage opener remote control)
# Feb 04, 2024, v1.4 [DIYable] - Refactored code to use class MqttPublishStats and class MqttGpioHardware
# Feb 06, 2024, v1.5 [DIYable] - Added onboard LED for status indicator passing method to WifiConnect() as delegate 
# Feb 08, 2024, v1.6 [DIYable] - Refactored code from camelCase and PascalCase to snake_case basaed on PEP (Python Enhancement Proposal)
# Feb 09, 2024, v1.7 [DIYable] - Fixed bug on log publishing error to Mqtt broker in reconnect scenario
# Feb 12, 2024, v1.8 [DIYable] - WIFI completely disconnected hangs on QoS1 (not able to fix, has to use QoS0 for this case)
# Feb 13, 2024, v1.9 [DIYable] - Rewrote code using mqtt_as (Thanks to Peter Hinch's amazing work on mqtt_as!) and uasyncio lib to solve problem of QoS1 socket hangs issue when WIFI is down

# References:
# https://github.com/micropython/micropython-lib/tree/master/micropython/umqtt.simple (very simple)
# https://peppe8o.com/mqtt-and-raspberry-pi-pico-w-start-with-mosquitto-micropython/  (machine.reset? really!)
# https://www.hivemq.com/blog/iot-reading-sensor-data-raspberry-pi-pico-w-micropython-mqtt-node-red/
# https://www.tomshardware.com/how-to/send-and-receive-data-raspberry-pi-pico-w-mqtt
# https://mpython.readthedocs.io/en/master/library/mPython/umqtt.simple.html
# https://github.com/micropython/micropython-lib/issues/103 (Qos1 sock WiFi is degraded)
# https://github.com/micropython/micropython/issues/2568 (Mqtt Wifi dropped, timeout)
# https://github.com/peterhinch/micropython-mqtt (Peter Hinch amazing "mqtt_as", the resilient asynchronous MQTT driver. Recovers from WiFi and broker outages)


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

# Convert Name(string to Pin(int)
# e.g. method("GP15") returns 15
def get_gp_name_to_pin(name):
    start = name.find(gpio_prefix)+len(gpio_prefix)
    end = len(name)
    return int(name[start:end])


# Set GPIO value on hardware
# e.g. method("GP15", 1) 
def set_gpio_value_on_hardware(name, value):
    # value = 0, 0V on output -> the led on PicoW board will be off, Relay = ON
    # value = 1, 3.3V on output -> the led on PicoW board will be on, Relay = OFF
    is_gpio_set = True
    message = ""
    global mqtt_publish_stats
        
    try:
        # Business logic to determine if hardware gpio should be set or not
        if ((time.time() - mqtt_gpio_hardware[name].last_modified_time) < hardware_modified_min_interval_in_seconds):
            is_gpio_set = False
            message = "Warning: Skipping Gpio {} value change for hardware burnout protection, min interval between value change is {} seconds".format(name, hardware_modified_min_interval_in_seconds)
            log(message)
            mqtt_publish_stats.is_force_publish = True
            
        if (((time.time() - mqtt_gpio_hardware[name].last_modified_time) < hardware_modified_threshold_in_seconds) and mqtt_gpio_hardware[name].modified_counter > hardware_modified_max):
            is_gpio_set = False
            mqtt_gpio_hardware[name].violation_counter = mqtt_gpio_hardware[name].violation_counter + 1    # Store total number of violation will lead to permanent fail
            message = "Warning: Skipping Gpio {} value change for hardware burnout protection, number of change exceeded max threshold {} in {} seconds".format(name, hardware_modified_max, hardware_modified_threshold_in_seconds)
            log(message)
            mqtt_publish_stats.is_force_publish = True
        elif (((time.time() - mqtt_gpio_hardware[name].last_modified_time) > hardware_modified_threshold_in_seconds) and mqtt_gpio_hardware[name].modified_counter > 0):
            mqtt_gpio_hardware[name].modified_counter = 0
            
        if (mqtt_gpio_hardware[name].violation_counter > hardware_violation_max + 1):
            message = "Error: Gpio {} value change is permanently disabled (until hardware reset) for protection, number of violation exceeded {}".format(name, hardware_violation_max)
            log(message)
            mqtt_publish_stats.is_force_publish = True
            mqtt_gpio_hardware[name].is_modified_allowed = False
            
        if (is_gpio_set == True):
            if (mqtt_gpio_hardware[name].is_modified_allowed == True):
                if (mqtt_gpio_hardware[name].is_momentary == True):
                    Pin(get_gp_name_to_pin(name), mode=Pin.OUT, value=0)  # On (0)
                    time.sleep(momentary_switch_delay_in_seconds)
                    Pin(get_gp_name_to_pin(name), mode=Pin.OUT, value=1)  # Off (1)
    
                    # Force publish for momentary switch - because if original status(int)=0, we switched to 1, then 0. 
                    # when we call is_gpio_values_changed() we are not able to detect the hardware change and client won't get updated
                    mqtt_publish_stats.is_force_publish = True  
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

               
# Print memory usage                
def print_memory_usage():
    print(f"Memory usage: {get_memory_usage()}")

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
            is_changed = True
            print ("GPIO hardware value is changed")
            
    return is_changed
           
          
# Log message printing it and also send to MQTT broker           
def log(message):
    print(message)
    global mqtt_publish_stats
    mqtt_publish_stats.log_messages.append(message)  # Save the message until next iteration in the loop to publish. If we call mqtt client here, race condition error
        
# Check if GPIO status should be published to MQTT broker   
def is_publish_gpio_status():

    is_publish = False
    is_changed = is_gpio_values_changed()   # Check if any GPIO hardware value has changed compare to master copy in dictionary
    
    # Business logic safeguard to disable publishing in case of error
    if (((time.time() - mqtt_publish_stats.last_published_time) < publish_threshold_in_seconds) and (mqtt_publish_stats.publish_counter > publish_counter_max)):
        # To test this case, set is_changed = True in is_gpio_values_changed() to flood the broker
        mqtt_publish_stats.publish_counter = -1
        log("Error: Abnormal number of publish detected in a short interval, publishing is stopped until hardware restart")                   
    elif  (((time.time() - mqtt_publish_stats.last_published_time) > publish_threshold_in_seconds) and mqtt_publish_stats.publish_counter >=0):
        mqtt_publish_stats.publish_counter = 0  
        
    # If is_first_time_run == True, publish a copy of all status to Mqtt broker
    # If publish_counter == -1 (error), it will skip publishing forever until hardware reset
    # If last_routine_published_time exceeded defined time, then publish
    # If is_force_publish == True, publish a copy of all status to Mqtt broker for force update (this is triggered by momentary relay in set_gpio_value_on_hardware)
    if (mqtt_publish_stats.is_first_time_run == True):
        mqtt_publish_stats.is_first_time_run = False
        log(f"Subscribed for ClientID: {mqtt_client_id.decode('utf-8')}")
        is_publish = True
    elif (is_changed == True and mqtt_publish_stats.publish_counter >= 0):	
        is_publish = True
    elif (((time.time() - mqtt_publish_stats.last_routine_published_time) > routine_publish_in_seconds) and routine_publish_in_seconds > 0):
        mqtt_publish_stats.last_routine_published_time = time.time()
        is_publish = True
    elif (mqtt_publish_stats.is_force_publish == True):
        mqtt_publish_stats.is_force_publish = False
        is_publish = True  
    
    return is_publish


# Get all GPIO status from the master dictionary for JSON publish
def get_all_gpio_status():    

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
        gpioStatus[name] = mqtt_gpio_hardware[name].status
    
    return gpioStatus


def get_memory_usage(full=False):
  gc.collect()
  F = gc.mem_free()
  A = gc.mem_alloc()
  T = F+A
  P = '{0:.2f}%'.format(A/T*100)
  if not full: return P
  else : return ('Total:{0} Free:{1} ({2})'.format(T,F,P))
  

# Publish Stats class to store all the global stats in mqtt_publish_stats
class PublishStats:    
    last_pinged_time = 0
    last_published_time = 0
    last_routine_published_time = 0
    publish_counter = 0
    is_force_publish = False
    is_first_time_run = False
    log_messages = []
    outage_counter = 0
    
# Define the property to used in the master dictonary mqtt_gpio_hardware    
class GpioProperty:
    status = 0   # status for all GPIO in 0 or 1  (Note this is the REVERSE of real pin to human readable, e.g. 0 = Off, 1 = On)
    pin = None   # Instance of real hardware pin object (Note: Low Voltage 0 = On,  High Voltage 1 = Off)
    last_modified_time = 0  # Last modified time for GPIO (only for relays to use only, hardware burnout protection)
    modified_counter = 0   # Modified counter for GPIO (only for relays to use only, hardware burnout protection)
    violation_counter = 0  # Violation counter for GPIO (only for relays to use only, hardware burnout protection)
    is_modified_allowed = False # Is hardware PIN is allowed to set (only for relays, hardware burnout protection)
    is_momentary = False       # Is hardware PIN is defined as momentary (only for relays, e.g. switch it on, it will turn off automatically)
               
               

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
                for key in json_object:
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
        blue_led(False)
        mqtt_publish_stats.outage_counter += 1
        print("WiFi or broker is down.")

async def up(client):
    while True:
        await client.up.wait()
        client.up.clear()
        blue_led(True)
        print(f"Connected for ClientID: {mqtt_client_id.decode('utf-8')}")
        await client.subscribe(mqtt_topic, mqtt_qos)
               

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
    mqtt_publish_stats.last_pinged_time = time.time() # For keep alive 
    mqtt_publish_stats.last_published_time = time.time()
    mqtt_publish_stats.last_routine_published_time = time.time()
    mqtt_publish_stats.publish_counter = 0    # If it's -1, it errors out and stops publishing forever
    mqtt_publish_stats.is_force_publish = False
    mqtt_publish_stats.is_first_time_run = True    # First time init to true
            

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
    try:
        await client.connect()
    except OSError:
        print('Connection failed.')
        return
    for task in (up, down, messages):
        asyncio.create_task(task(client))

    while True:
        await asyncio.sleep(5)

        # If WiFi is down the following will pause for the duration.
        # await client.publish(mqtt_topic, '{} repubs: {} outages: {}'.format(n, client.REPUB_COUNT, mqtt_publish_stats.outage_counter), qos = 1)

        # Uncomment this to Delete all RETAIN messages from the MQTT broker (e.g. if you accidentially set the retain flag in "Iot MQTT Panel" app)
        # client.publish(mqtt_topic, '', True)
        
        # Publish log (not updating publish_counter and last_published_time)
        # Notes: If logs are published in callback, it will error out in mqtt broker reconnect scenario
        if (mqtt_publish_stats.log_messages is not None):
            for x in mqtt_publish_stats.log_messages:
                await client.publish(mqtt_topic, x, mqtt_retain, mqtt_qos)  #QoS=1, Retain flag=false
                mqtt_publish_stats.log_messages = []
                                
        # Check GPIO hardware changes and with other conditions are met, then publish JSON
        if (is_publish_gpio_status() == True):
            mqtt_publish_stats.publish_counter = mqtt_publish_stats.publish_counter + 1 
            mqtt_publish_stats.last_published_time = time.time()
            jsonStatus = json.dumps(get_all_gpio_status())   # JSON message
            await client.publish(mqtt_topic, jsonStatus, mqtt_retain, mqtt_qos)  #QoS=1, Retain flag=false            


#  ----------------------------------------------------------------------------

mqtt_publish_stats = None
mqtt_gpio_hardware = None
init()

# Set up client. Enable optional debug statements.
MQTTClient.DEBUG = True
client = MQTTClient(config)

try:
    print_memory_usage()
    asyncio.run(main(client))
finally:  # Prevent LmacRxBlk:1 errors.
    print("Shutting down....")
    print_memory_usage()        
    blue_led(False)
    client.close()
    asyncio.new_event_loop()



