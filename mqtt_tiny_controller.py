import network,urequests, utime, ubinascii, ntptime
import json, re, gc, os, machine
import uasyncio as asyncio
from machine import Pin
from collections import OrderedDict
from mqtt_as import MQTTClient, config
from mqtt_tiny_controller_config import *
from mqtt_tiny_controller_common import *
from mqtt_local import *
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
# Feb 23, 2024, v2.0.5 [DIYable] - Response public IP in JSON format with customized key name, this can be useful for Serverless Azure Function or AWS Lambda to update domain using dynamic DNS service
# Feb 25, 2024, v2.0.6 [DIYable] - Sync internal clock with NTP server, refactored time to utime. Added notification JSON as part of the log {"NOTIFY": {"GP16": 1, "GP17": 0}}
# Feb 26, 2024, v2.1.0 [DIYable] - Added Multi-Factor Authentication (MFA) using Time-Based One-Time Passwords (TOTP) with support for multiple keys for each GPIO. 
# Feb 28, 2024, v2.1.1 [DIYable] - Bug fix on notification and send back changed values to the broker regardless. Refactored the code.
# Mar 04, 2024, v2.2.0 [DIYable] - Publish last publish time stamp to MQTT as log, each time microcontroller publishes GPIO values
# Mar 17, 2024, v2.2.1 [DIYable] - Configurable momentary relay wait for x seconds before switching off, support concurrent non-blocking GPIO value change using async call
# Mar 20, 2024, v2.2.2 [DIYable] - Issue with the asynchronous message callback where it confuses responses with requests in async calls. Refactored the code to distinguish between REQUEST and RESPONSE.
# Mar 21, 2024, v2.2.3 [DIYable] - Removed request/response in JSON and use "UTC" in JSON message to identify if it's a response during call back. It's because mobile app "IoT MQTT Panel", publish message in a switch has to be in same pattern as JSON subscribe.
# Apr 06, 2024, v2.2.4 [DIYable] - Minor bug fix and cleaned up and made get_stats become async call, log when wifi/broker disconnect/connect
# May 06, 2024, v2.2.5 [DIYable] - Fixed bug on JSON ordering when request includes MFA in the payload, the order can be wrong. e.g. {"MFA":644133, "GP26": 1, "GP27": 1}. Before fix, GP27 may run first.

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

def get_gpio_merged_list():
    merged_list = gpio_pins_for_relay_switch.copy()
    merged_list.update(gpio_pins_for_momentary_relay_switch)    
    merged_list.update(gpio_pins_for_contact_switch)
    return merged_list

                
# Flip 0 to 1 and 1 to 0 because of Pin.PULL_UP (for both contacts and relays), disconnected = 1 and connected = 0
# We need to flip it reverse to connected = 1 and disconnected = 0 (more human readable)
# e.g method(0) returns 1
def flip_value(value):
     if (value == 1):
        return 0
     if (value == 0):
        return 1

# Set GPIO value on hardware
# e.g. method("GP15", 1) 
async def set_gpio_value_on_hardware(name, value):
    
    # This is more to set GPIO on/off for Relay
    # value = 0, 0V on output -> the breakout board GPIO(x) LED and relay(x) LED will be off, Relay(x) = ON
    # value = 1, 3.3V on output -> the breakout board GPIO(x) LED and relay(x) LED will be on, Relay(x) = OFF
    
    is_gpio_set = True
    message = ""
    global mqtt_publish_stats
        
    try:
        # Business logic to determine if hardware gpio should be set or not
        if ((utime.time() - mqtt_gpio_hardware[name].last_modified_time) < hardware_modified_cooldown_period_in_seconds):
            is_gpio_set = False
            message = f"Warning: Skipping Gpio {name} value change for hardware burnout protection, min interval between value change is {hardware_modified_cooldown_period_in_seconds} seconds"
            log(message)
            mqtt_publish_stats.is_republish = True   # Since we are ignoring the changes, client needs to be updated by republish
            
        if (((utime.time() - mqtt_gpio_hardware[name].last_modified_time) < hardware_modified_threshold_in_seconds) and mqtt_gpio_hardware[name].modified_counter > hardware_modified_max):
            is_gpio_set = False
            mqtt_gpio_hardware[name].violation_counter = mqtt_gpio_hardware[name].violation_counter + 1    # Store total number of violation will lead to permanent fail
            message = f"Warning: Skipping Gpio {name} value change for hardware burnout protection, number of change exceeded max threshold {hardware_modified_max} in {hardware_modified_threshold_in_seconds} seconds"
            log(message)
            mqtt_publish_stats.is_republish = True   # Since we are ignoring the changes, client needs to be updated by republish
        elif (((utime.time() - mqtt_gpio_hardware[name].last_modified_time) > hardware_modified_threshold_in_seconds) and mqtt_gpio_hardware[name].modified_counter > 0):
            mqtt_gpio_hardware[name].modified_counter = 0
            
        if (mqtt_gpio_hardware[name].violation_counter > hardware_violation_max + 1):
            message = f"Error: Gpio {name} value change is permanently disabled (until hardware reset) for protection, number of violation exceeded {hardware_violation_max}"
            log(message)
            mqtt_publish_stats.is_republish = True   # Since we are ignoring the changes, client needs to be updated by republish
            mqtt_gpio_hardware[name].is_modified_allowed = False
            
        if (len(mqtt_gpio_hardware[name].totp_keys) > 0):
            print (f"MFA TOTP keys found for {name}")
           
            is_mfa_passed = False
            for secret_key in mqtt_gpio_hardware[name].totp_keys:                
                try:
                    totp_number_list = get_totp(secret_key, totp_max_expired_codes)  # Get a list of current code and expired codes
                    print(f"TOTP List={totp_number_list}")

                    if (mqtt_publish_stats.totp_number in totp_number_list):
                        print("MFA TOTP matched, hardware value change is allowed")
                        is_mfa_passed = True   # There are multiple keys (for multiple clients), one matches means passed
                        break
                except Exception as e:
                    print(f"Error in getting or matching TOTP={e}")
                    pass
                
            if (is_mfa_passed == False):
                is_gpio_set = False
                message = f"Error: MFA validation failed, GPIO cannot be set."
                log(message)
                mqtt_publish_stats.is_republish = True   # Since we are ignoring the changes, client needs to be updated by republish

            
        if (is_gpio_set):
            if (mqtt_gpio_hardware[name].is_modified_allowed):
                time_called = utime.time()
                if (mqtt_gpio_hardware[name].is_momentary):                    
                    Pin(get_gp_name_to_pin(name), mode=Pin.OUT, value=0)  # On (0)
                    await asyncio.sleep(mqtt_gpio_hardware[name].momentary_wait_in_seconds) # Non-blocking sleep for x seconds                   
                    Pin(get_gp_name_to_pin(name), mode=Pin.OUT, value=1)  # Off (1), Publish this GPIO is needed because PIN returns to the original state                    
                else:
                    Pin(get_gp_name_to_pin(name), mode=Pin.OUT, value=flip_value(value)) # Regular relay switch
                mqtt_gpio_hardware[name].is_changed = True  # Any hardware change needs to echo back to borker making sure client has the same value
                    
                mqtt_gpio_hardware[name].last_modified_time = time_called   # Because of momentary wait, we need to use the time when it was called, not after the delay
                mqtt_gpio_hardware[name].modified_counter = mqtt_gpio_hardware[name].modified_counter + 1
        
        # GPIO hardware status update
        update_gpio_status_from_hardware(name)
        
    except KeyError as ke:
         pass
    
               
# Check if the hardware GPIO value are different from in memory GPIO in dictionary
def is_gpio_values_changed():    
    is_changed = False    
    merged_list = get_gpio_merged_list()
       
    # Publish if memory value is different from the hardware GPIO value
    for x in merged_list:
        name = gpio_prefix+str(x)
        if (get_current_gpio_value(name) != get_gpio_value_from_hardware(name)):   # This is for PIN.IN such as contact switches          
            update_gpio_status_from_hardware(name)
            mqtt_gpio_hardware[name].is_changed = True
            is_changed = True
            print ("GPIO hardware value has changed")
        elif (mqtt_gpio_hardware[name].is_changed):   # THis is for PIN.OUT such as relay (the is_changed flag already set)
            is_changed = True
            print ("GPIO value was changed (momentary switch)")
            
    return is_changed
  
# Check if GPIO status should be published to MQTT broker   
def is_publish_gpio_status(is_goip_changed):

    is_publish = False
    is_full = False
   
    # Business logic safeguard to disable publishing in case of error
    if (((utime.time() - mqtt_publish_stats.last_published_time) < publish_threshold_in_seconds) and (mqtt_publish_stats.publish_counter > publish_counter_max)):
        # To test this case, set is_changed = True in is_gpio_values_changed() to flood the broker
        mqtt_publish_stats.publish_counter = -1
        log("Error: Abnormal number of publish detected in a short interval, publishing is stopped until hardware restart")                   
    elif  (((utime.time() - mqtt_publish_stats.last_published_time) > publish_threshold_in_seconds) and mqtt_publish_stats.publish_counter >=0):
        mqtt_publish_stats.publish_counter = 0  
           
    # Publish full list status to Mqtt broker first time running or republish (command is called "refresh"), otherwise only send the changed values
    if (mqtt_publish_stats.is_first_time_run):   
        mqtt_publish_stats.is_first_time_run = False
        log(f"Subscribed for ClientID: {mqtt_client_id.decode('utf-8')}")
        print("Publish (First time), send full list")
        is_publish = True
        is_full = True
    elif (mqtt_publish_stats.is_republish):                
        mqtt_publish_stats.is_republish = False
        print("Publish (Republish), send full list")
        is_publish = True
        is_full = True
    elif (((utime.time() - mqtt_publish_stats.last_scheduled_published_time) > scheduled_publish_in_seconds) and scheduled_publish_in_seconds > 0):
        mqtt_publish_stats.last_scheduled_published_time = utime.time()    # If last_scheduled_published_time exceeded defined time, then publish
        print("Publish (Scheduled), send full list")
        is_publish = True        
        is_full = True
    elif (is_goip_changed and mqtt_publish_stats.publish_counter >= 0): # If publish_counter == -1 (error), it will skip publishing forever until hardware reset
        print("Publish (Changed), only send changed values")
        is_publish = True
        is_full = False  # Only publish changed values
        
    return is_publish, is_full


# Get all GPIO status from the master dictionary for JSON publish
def get_gpio_status(full=False):    

    gpio_status = OrderedDict()
    
    # Get the list in sorted order because of leading 0 integer won't work in string sorted (i.e. GP1, GP16, GP2) 
    merged_list = get_gpio_merged_list()

    # Get the list of integer (ToDo: refactor needed - maybe there is a better way to do this in Python)
    temp_list = []
    for a in merged_list:
        temp_list.append(a)

    # Sort the integer and then combined into OrderedDict, regular dictionary won't sort properly with JSON.dumps()
    for x in sorted(temp_list):        
        name = gpio_prefix+str(x)
        if (full == False):
            if (mqtt_gpio_hardware[name].is_changed):
                gpio_status[name] = mqtt_gpio_hardware[name].status                            
        else:
            gpio_status[name] = mqtt_gpio_hardware[name].status
        
    return gpio_status


# Reset all changed GPIO status
def reset_gpio_changed_status():
    
    merged_list = get_gpio_merged_list()
       
    for x in merged_list:
        name = gpio_prefix+str(x)
        if (mqtt_gpio_hardware[name].is_changed):
            mqtt_gpio_hardware[name].is_changed = False 
            
# Send notification if it meets the conditions            
def send_notification(is_gpio_changed):
    
    if (is_gpio_changed):
        
        # Note: In an ideal world, sending a separate message would not be needed, as it would be the responsibility of the client to detect value changes
        #       if the client application supports notifications. However, client applications may reset values to their defaults, potentially resulting in false positive notifications.
        #       In such cases, reliance on the microcontroller's value as the single source is not a bad idea.

        print(f"Notification is called, GPIO has changed. Only configured GPIO will receive notification.")
        changed_gpio_status = get_gpio_status(False) # True = full list, False = only changed values
        
        # Send notification response for changed values
        is_notify = False
        temp_gpio = OrderedDict()

        # Only send notificaiton for the pins configured to be sent
        for gpio_name in changed_gpio_status:
            pin_id = get_gp_name_to_pin(gpio_name)  # Get the name to pin id (e.g. from "GP2" to 2)
            if (pin_id in gpio_pins_for_notification):  # Check the list in config (only send if it matches in config list)
                is_notify = True
                temp_gpio[gpio_name] = changed_gpio_status[gpio_name] # copy the value 
                
        if (is_notify):
            notification_dict = dict()
            notification_dict[notification_keyname]=temp_gpio   
            log(json.dumps(notification_dict))  # format it and converted to JSON: e.g. {"NOTIFY": {"GP16": 1}} or {"NOTIFY": {"GP16": 1, "GP17": 0}}
          
 
          
# Log message printing it and also send to MQTT broker           
def log(message):
    print(message)
    global mqtt_publish_stats
    mqtt_publish_stats.log_messages.append(message)  # Save the message until next iteration in the loop to publish. If we call mqtt client here, race condition error
        

#  ----------------------------------------------------------------------------          
    
# Get the stats such as uptime and outages
async def get_stats():    
    error_message = None
    try:
        total_uptime = (utime.time() - mqtt_publish_stats.startup_time)
        uptime_days, uptime_hours, uptime_minutes, uptime_seconds = calculate_time(total_uptime)
        log(f"Uptime={uptime_days} days {uptime_hours} hrs, Outages={mqtt_publish_stats.outage_counter}, Mem={get_formatted_memory_usage()}, Temp={get_formatted_temperature()}, UTC={get_formatted_utc_time_now()}")        
    except Exception as e:
        error_message = f"Exception to get stats: {e}"

    if (error_message != None):
        log(error_message)
        
# Get public ip. Note: this is an async call so it won't block
async def get_public_ip():
    public_ip = None
    error_message = None
    try:
        temp_ip = get_public_ip_from_provider(json_ip_provider)
        public_ip = json.dumps({ip_keyname:temp_ip}) # Customized key name for JSON result  
    except Exception as e:
        error_message = f"Exception to get IP: {e}"
        
    if (error_message != None):
        log(error_message)
        
    if (public_ip != None):        
        log(public_ip)
    
    
# This scheduled_sync_clock is non-blocking, it is used for scheduled sync.     
async def scheduled_sync_clock():
    global mqtt_publish_stats
    try:
        ntptime.settime()
        mqtt_publish_stats.last_clock_synced_time = utime.time()
        log(f"Clock synced, timestamp={utime.time()}" )
    except Exception as e:
        log(f"Error synchronizing clock: {e}")
    finally:
        log(f"UTC={get_formatted_utc_time_now()}")
    

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
    last_clock_synced_time = 0
    totp_number = 0  # This stores the global 6 digit totp number (sent by the client app)
    
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
    totp_keys = []  # Each GPIO can have multiple keys allowed to access (e.g. Azure function Mqtt vs Mqtt mobile app)
    momentary_wait_in_seconds = 0  # For momentary switch (customized wait in x seconds before switching it off)

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
           ordered_json_data = {}   # Ordered json by key
           for key in sorted(json_object.keys()):
               ordered_json_data[key] = json_object[key]           
           is_message_json = True
        except ValueError as ve:
           is_message_json = False
           
        if (is_message_json):
            try:
                is_message_response = False   # Is Message a Request (sent from client) or a Response (sent from microcontroller), using UTC as identifier
                
                 # Because of call back, we need to ignore {"IP":"111.222.333.444"} or {"NOTIFY": {"GP16": 1, "GP17": 0}} or {"GP21":1, "UTC":"2024-01-01"}
                for key in ordered_json_data:
                    if ((key == ip_keyname) or (key == notification_keyname) or (key == utc_keyname)):
                        is_message_response = True
                        print("JSON is a response, ignore in callback")
                        break
                
                if(is_message_response == False):                    
                    # Json objects are not in order, need seperated loop to set MFA if it's part of GPIO message, e.g. {"GP16":1, "MFA":123456}
                    for key in ordered_json_data:
                        if (key == totp_keyname):
                            mqtt_publish_stats.totp_number = int(ordered_json_data[key])  # 6 digit integer (not string)
                            break
                    
                    for key in ordered_json_data:    
                        if (key == command_keyname):   
                            # Command in Json received, e.g {"CMD":"getip"}
                            # Note: key in a dict is unique, e.g. Multiple commands like this {"CMD": "getip", "CMD": "stats", "CMD": "refresh"} will only execute "refresh" (last item)            
                            cmd_value = ordered_json_data[key]                        
                            if (commands[cmd_value] == 501):  # Use dict as enum without hardcoding
                                asyncio.create_task(get_stats())  # Async call to get stats
                            elif (commands[cmd_value] == 502):
                                mqtt_publish_stats.is_republish = True    # Note: CMD "refresh", set republish next round
                            elif (commands[cmd_value] == 503):
                                asyncio.create_task(get_public_ip())  # Async call to get Ip address
                        elif ((key != totp_keyname) and key.startswith(gpio_prefix)):
                            value = ordered_json_data[key] # e.g. {"GP16":1, "GP17":0}
                            if (get_current_gpio_value(key) != value):
                                print(f"Async set value on hardware key={key}, value={value}")
                                asyncio.create_task(set_gpio_value_on_hardware(key, value))  # Async call to set multiple hardware (e.g. multiple relays) at the same time
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
        log(f"WiFi or broker is down, UTC={get_formatted_utc_time_now()}")
        print("WiFi or broker is down.")

async def up(client):
    while True:
        await client.up.wait()
        client.up.clear()
        mqtt_publish_stats.is_online = True
        log(f"Connected: {mqtt_client_id.decode('utf-8')}, UTC={get_formatted_utc_time_now()}")
        print(f"Connected: {mqtt_client_id.decode('utf-8')}")
        await client.subscribe(mqtt_topic, mqtt_qos)
        
async def onboard_led_online_status():
    while True:
        if (mqtt_publish_stats.is_online):
            set_onboard_led(True)
        else:
            toggle_onboard_led()
        await asyncio.sleep(1)
    
#  ----------------------------------------------------------------------------      
# init mqtt_as using config[] as per original library

def init_mqtt_as():
    
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
    
    
# init in-memory dict and stats    
def init():
    
    global mqtt_publish_stats
    global mqtt_gpio_hardware    
    
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
        mqtt_gpio_hardware[name].last_modified_time = utime.time() # only for relay
        mqtt_gpio_hardware[name].modified_counter = 0 # only for relay
        mqtt_gpio_hardware[name].violation_counter = 0 # only for relay
        mqtt_gpio_hardware[name].is_modified_allowed = True # only for relay
        
        if (x in gpio_pins_for_momentary_relay_switch):
            mqtt_gpio_hardware[name].is_momentary = True
            mqtt_gpio_hardware[name].momentary_wait_in_seconds = momentary_switch_default_wait_in_seconds   # Default is set to 2 secs
            try:
                if (gpio_pins_for_momentary_relay_switch[x] is not None):
                    mqtt_gpio_hardware[name].momentary_wait_in_seconds = gpio_pins_for_momentary_relay_switch[x]  # Set customized wait (in seconds) for momentary relay
            except:
                pass            
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

    # TOTP
    for z in gpio_pins_for_totp_enabled:
        name = gpio_prefix+str(z)
        mqtt_gpio_hardware[name].totp_keys = gpio_pins_for_totp_enabled[z]
                
        
    # init stats
    mqtt_publish_stats = PublishStats()    
    mqtt_publish_stats.last_published_time = utime.time()
    mqtt_publish_stats.last_scheduled_published_time = utime.time()
    mqtt_publish_stats.publish_counter = 0    # If it's -1, it errors out and stops publishing forever
    mqtt_publish_stats.is_republish = False
    mqtt_publish_stats.is_first_time_run = True    # First time init to true
    mqtt_publish_stats.startup_time = utime.time()
    mqtt_publish_stats.is_online = False   # For onboard LED to use
    mqtt_publish_stats.last_clock_synced_time = utime.time()  # NOTE: becuase we ran the startup_clock_sync(), without error we assume at this point we have the clock synced successfully
    mqtt_publish_stats.totp_number = 0    # This stores the global 6 digit totp number (sent by the client app)

#  ----------------------------------------------------------------------------      
# Worker for infinite while loop

# Technical notes on wifi/broker test:
#
# Case 1: Auto re-connect when network fails:  
#    Use firewall rules on your router to block traffic to broker after connection is established 
# Case 2: Auto re-connect when Wifi fails (SSID is still available)    
#    Disconnect your PicoW using router admin
# Case 3: Auto re-connect when Wifi totally gone (SSID is NOT available)
#    Power off the router or change the SSID name of WiFi

async def worker(client):

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
        
        # Non-blocking NTP clock sync
        if (((utime.time() - mqtt_publish_stats.last_clock_synced_time) > scheduled_clock_sync_in_seconds) and scheduled_clock_sync_in_seconds > 0):
            asyncio.create_task(scheduled_sync_clock())       
        
        # Publishing of LOG and GOIP values are in two different steps
        # Because we are not updating publish_counter or last_published_time for log
        # Also, log can be seperated into a different MQTT topic if needed in the future
                
        # Publishing of LOG:
        # Notes: If client.publish is called in callback, it will error out in mqtt broker reconnect scenario. Do it here.
        if (mqtt_publish_stats.log_messages is not None):
            for x in mqtt_publish_stats.log_messages:                
                await client.publish(mqtt_topic, x, mqtt_retain, mqtt_qos)  #QoS=1, Retain flag=false
                mqtt_publish_stats.log_messages = []                    

        # Publishing of GPIO and Notification:
        # Check if any GPIO hardware value(s) has changed compare to master copy in dictionary
        is_gpio_changed = is_gpio_values_changed()           
        send_notification(is_gpio_changed)      # Notification if necessary
        is_publish, is_full = is_publish_gpio_status(is_gpio_changed)  # Full list or partial list to Mqtt broker based on business logic 
              
        if (is_publish):
            json_gpio_status = None  # this json contains either full list of GPIO status values or partial list of changed values  
                        
            if (is_full):
                all_gpio = get_gpio_status(True) # Get the full list in JSON
                all_gpio[utc_keyname] = get_formatted_utc_time_now()                
                json_gpio_status = json.dumps(all_gpio)                
            else:
                all_gpio = get_gpio_status(False) # Get the list of changed values in JSON
                all_gpio[utc_keyname] = get_formatted_utc_time_now()                
                json_gpio_status = json.dumps(all_gpio)
                reset_gpio_changed_status()  # Reset is_changed to False            

            mqtt_publish_stats.publish_counter = mqtt_publish_stats.publish_counter + 1 
            mqtt_publish_stats.last_published_time = utime.time()
            # log(f"Last GPIO Published={get_formatted_utc_time_now()}") # Log the last published time stamp and send to broker (purely for logging purpose)
            
            await client.publish(mqtt_topic, json_gpio_status, mqtt_retain, mqtt_qos)  #QoS=1, Retain flag=false
            
            
            

#  ----------------------------------------------------------------------------
# Program main 

mqtt_publish_stats = None
mqtt_gpio_hardware = None

# Note: The "mqtt_as" library operates under the assumption of a stable connection during startup. However, it faces
#       the risk of permanent termination if the WiFi signal is weak during the initial startup or after a reboot following
#       a power outage where the WiFi is not yet available.
# Workaround: To mitigate this issue, a retry loop has been implemented before invoking the "mqtt_as" code.

wlan = connect_wifi(toggle_onboard_led)   # pass "toggle_onboard_led" as delegate
if wlan.isconnected():             

    # Use NTP server to sync the internal clock
    sync_clock()   # This sync_lock is blocking (not async), it's in the _common lib only use 1 time when starting up
    init()         # If there is any error in clock sync, we use the default RTC start time: Jan 1, 2021 (TOTP will fail though)

    # Init config[] for mqtt_as
    init_mqtt_as()

    # Set up client. Enable optional debug statements.
    MQTTClient.DEBUG = True
    client = MQTTClient(config)

    try:
        print(f"Memory usage: {get_formatted_memory_usage()}")
        asyncio.run(worker(client))
    finally:  # Prevent LmacRxBlk:1 errors.
        print("Shutting down....")
        print(f"Memory usage: {get_formatted_memory_usage()}")
        set_onboard_led(False)    # PicoW has only one LED 
        client.close()
        asyncio.new_event_loop()
