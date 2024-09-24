
# Common library for mqtt_tiny_controller

import ntptime, utime, network, urequests, machine
import json, re, gc, os
from mqtt_tiny_controller_config import *
from pico_2fa_totp import *

# Start up loop for connecting wifi
def connect_wifi(toggle_onboard_led_delegate):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.config(pm = 0xa11140) # Diable powersave mode
    wlan.connect(wifi_ssid, wifi_pass)

    max_wait = wifi_max_retries
    while max_wait > 0:
        toggle_onboard_led_delegate()       # Note: Cannot call asnyc function onboard_led_online_status() before "mqtt_as" starts
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        max_wait -= 1     
        print('Device started: Waiting for connection...')
        utime.sleep(1)        
    
    if wlan.status() != 3:
        # raise RuntimeError('Wifi connection permanently Failed')        
        print('Wifi connection permanently Failed, machine will reboot...')
        utime.sleep(wifi_reset_delay_in_seconds)        
        machine.reset()
    else:
        print('Wifi Connected')
        print(wlan.ifconfig())
        
    return wlan
        

# Get wifi strength in percentage with given ssid
def get_formatted_wifi_strength(wlan, ssid):
    
    wifi_strength = 0
    try:
        # Get rssi from wlan. Notes: wlan.status('rssi') does not work on PicoW, it has to do a scan
        networks = wlan.scan()  # Scans for networks        
        rssi = get_rssi_for_ssid(networks, ssid)
        
        if rssi is not None:            
            # Define the range of RSSI values (based on general Wi-Fi standards)
            max_rssi = -30  # Best signal strength (100%)
            min_rssi = -90  # Worst signal strength (0%)
            
            # Cap the rssi value within the defined range
            if rssi <= min_rssi:
                return 0
            elif rssi >= max_rssi:
                return 100
            
            # Translate RSSI to a percentage
            wifi_strength = int((rssi - min_rssi) * 100 / (max_rssi - min_rssi))
        else:
            wifi_strength = -1  # SSID not found
        
    except Exception as e:
        wifi_strength = -1 # Any other errors
        
    return (f"{wifi_strength}%")


# Look for the RSSI from SSID network array
def get_rssi_for_ssid(networks, target_ssid):
    for network in networks:
        ssid, bssid, channel, rssi, authmode, hidden = network
        if ssid == target_ssid:
            return rssi
    return None  # Return None if SSID not found
       

# Function to check if DST applies (Second Sunday of March to First Sunday of November)
def is_dst(year, month, day):
    if month > 3 and month < 11:
        return True
    if month == 3:
        second_sunday = 14 - (utime.localtime(utime.mktime((year, 3, 1, 0, 0, 0, 0, 0)))[6])
        return day >= second_sunday
    if month == 11:
        first_sunday = 7 - (utime.localtime(utime.mktime((year, 11, 1, 0, 0, 0, 0, 0)))[6])
        return day < first_sunday
    return False

# Function to format time tuple into 'YYYY-MM-DD HH:MM:SS'
def format_time(time_tuple, time_zone_name):
    return "{:04}-{:02}-{:02} {:02}:{:02}:{:02} {}".format(
        time_tuple[0], time_tuple[1], time_tuple[2],
        time_tuple[3], time_tuple[4], time_tuple[5],
        time_zone_name
    )

# Function to get formatted time based on time zone
def get_formatted_time_now(time_zone_name):
    utc_time = utime.time()  # Get current UTC time (in seconds since epoch)

    if time_zone_name == "UTC":
        utc_time_tuple = utime.localtime(utc_time)
        return format_time(utc_time_tuple, time_zone_name)

    elif time_zone_name == "EST":  # Only supports EST, implement your own time zone if you wish
        local_time = utime.localtime(utc_time)
        year, month, day = local_time[0], local_time[1], local_time[2]

        # EST is UTC-5, EDT is UTC-4 (DST)
        offset = -5 if not is_dst(year, month, day) else -4

        # Adjust time for the EST/EDT offset
        est_time = utime.localtime(utc_time + offset * 3600)

        return format_time(est_time, time_zone_name)

    else:
        return "Unsupported time zone"

    
# Get memory usage to check memory leak 
def get_formatted_memory_usage(full=False):
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


# Get IP address from provider
def get_public_ip_from_provider(json_provider):
    result_ip = None
    response = urequests.get(json_provider)
    if response.status_code == 200:
        data = response.json()
        result_ip = data.get('ip', None)   # Json ip provider look for "ip"        
    return result_ip

# MFA get TOTP with key return a list of existing code and expired code allowed
# Returns e.g. [105687, 124004, 13357, 168469, 211798]
def get_totp(secret_key, number_of_expired_code_allowed, step_secs=30):
    result_list  = []
    value = 0
    for x in range(number_of_expired_code_allowed):           
        result_list.append(int((totp(utime.time() + value, secret_key))[0]))
        value -= step_secs        
    return result_list
