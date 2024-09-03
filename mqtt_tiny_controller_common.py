
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

# Sync clock at startup
def sync_clock():    
    try:
        ntptime.settime()        
        print(f"Synced clock successfully, timestamp={utime.time()}" )
    except Exception as e:
        print(f"Error synchronizing clock: {e}")
    finally:
        print(f"Rtc={get_formatted_utc_time_now()}")
        
# Get formatted UTC time
def get_formatted_utc_time_now():
    t = utime.gmtime()
    formatted_time = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(t[0], t[1], t[2], t[3], t[4], t[5])
    return(formatted_time)
    
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
