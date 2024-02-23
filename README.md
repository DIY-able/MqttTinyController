# MqttTinyController
MqttTinyController runs on Raspberry Pi PicoW (RP2040) using any free cloud MQTT broker (e.g. HiveHQ or Mosquitto) to control home automation relay switches and contact switches. Support JSON payload for free mobile app such as "IoT MQTT Panel".

# Project
Many of the MQTT PicoW codes, samples, and tutorials available on the Internet lack the robustness required to handle real-life disasters. They often fall short, either being overly simplistic or lacking essential features. This code is designed to meet the demands of DIY enthusiasts, it has undergone extensive testing to ensure reliability, it's stable to run 24/7 at home. 

It was originally based on umqtt.simple, umqtt.robust but both of the libraries FAILED so badly in my test cases, later during the development cycle, the code was re-written using "mqtt_as" library and asyncio library. The final product is capable of operating continuously without interruption, even in the face of potential threats such as hacking attempts targeting your MQTT client account to manipulate relay toggling and potentially starts a fire in your home, this offers a layer of protection. While the code may not be entirely bulletproof, your input and contributions for enhancement are greatly appreciated. Please feel free to share any improvements you identify to help advance this project.

# Thanks to Peter Hinch on mqtt_as.py and mqtt_local.py
Thanks to the amazing "mqtt_as" library written by Peter Hinch from UK. Forget about umqtt.simple and umqtt.robust, mqtt_as is totally on another level. Together with uasyncio library, it solves every problem I had.
Github: https://github.com/peterhinch/micropython-mqtt 

# Features
- Support relay switches (e.g. appliance control) and contact switches (e.g. magnetic contact)
- Capability to configure relay switches as momentary switches (e.g. garage doors with press/release functionality on remote control)
- Only one single MQTT Topic is needed for both publishers and subscribers with the use of JSON.
- Structure MQTT payload in JSON format to facilitate compatibility with mobile app "IoT MQTT Panel" leveraging JSON Path.
- Automatic WiFi reconnection functionality to seamlessly reconnect in case of disconnection. (Thanks to Peter Hinch on mqtt_as library)
- Automatic reconnection to the MQTT broker to maintain uninterrupted communication. (Thanks to Peter Hinch on mqtt_as library)
- Quality of Service (QoS) level 1 to guarantee no message loss even in the event of MQTT broker downtime or WiFi disconnection.
- Utilize the onboard LED to provide clear visual status indications: Operational, System halted or Connecting
- Implement hardware safeguards to prevent relay burnout caused by flooded incoming messages in a single batch, such as after WiFi reconnection. (Alternatively, you can use Peter Hinch's mqtt_as config["clean_init"])
- Integrate hardware safeguards to prevent relay burnout in scenarios of excessive toggling, automatically resuming operation after a predefined interval.
- Implement hardware safeguards to prevent message acceptance until a hardware reset if a predefined violation threshold is reached.
- Ensure data usage protection by halting MQTT message publishing in the event of a fatal error until a hardware reset is performed.
- Option to regularly publish hardware status to MQTT broker, broadcasting to all clients at predefined intervals for comprehensive monitoring and control.
- Retrieve statistics such as total uptime and outage occurrences.
- Obtain temperature readings using the onboard sensor of the Pico.
- Retrieve the public IP address of your router.

# Hardware
- Raspberry Pi PicoW Pre-Soldered Header (e.g. Freenove FNK0065C from Amazon)
- 4Channel Relay Module (e.g. Sainsmart ‎101-70-101 from Amazon)
- Pico Breakout Board (e.g. Freenove FNK0081 from Amazon)

# Does the code work on ESP32, ESP8266, Pyboard?
Only tested on Raspberry PicoW. The onboard LED and tempeature sensor code has been moved to mqtt_local.py (inherited from mqtt_as project). Minor code changes or implementation maybe needed, it would be nice to abstract all the hardware calls to support all microcontrollers (contribution is welcome!). Other than that, I believe the rest of the code should be compatiable.

# umqtt.simple(1or2) umqtt.robust(1or2) memory leak fix
Originally, this project relies on the "micropython-umqtt.simple" library for its operation. However, navigating through its various versions like "umqtt.simple2," "umqtt.robust," or "umqtt.robust2" might lead to confusion. Unfortunately, all four libraries suffer from memory leaks or frozen issues. To illustrate, both "umqtt.simple" (with try/except reconnect) and "umqtt.robust" for auto-reconnect failed to pass my test cases on Raspberry Pi Pico W. While they managed to reconnect successfully, they persisted in experiencing memory leaks after several disconnect/reconnect cycles.  Eventually, it will lead to "out of memory" error:

       Traceback (most recent call last):
       File "<stdin>", line 47, in <module>
       OSError: [Errno 12] ENOMEM

or RTOS heap memory after reconnecting during SSL handshake

       Traceback (most recent call last):
       File "<stdin>", line 63, in <module>
       OSError: (-10368, 'MBEDTLS_ERR_X509_ALLOC_FAILED')

Although I was able to fix that, there are more problems on the test case 3:

- Case 1: Auto re-connect when network fails:  Use firewall rules on your router to block traffic to broker after connection is established 
- Case 2: Auto re-connect when Wifi fails (SSID is still available): Disconnect your PicoW using router admin
- Case 3: Auto re-connect when Wifi totally gone (SSID is NOT available): Power off the router or change the SSID name of WiFi

If you are using QoS1 on Case 3, the socket will hang indefinitely. However, if you are using QoS0, it is fine but it defeats the purpose. The cause is the library uses blocking sockets with no timeout, Qos1 got stuck in wait_msg. It has been well documented in 2016:

- https://github.com/micropython/micropython-lib/issues/103 (Qos1 sock WiFi is degraded)
- https://github.com/micropython/micropython/issues/2568 (Mqtt Wifi dropped, timeout)

Solution: Use "mqtt_as" library written by Peter Hinch. It passed all my test cases with QoS1.

# Important notes on QoS1 with Clear Session
In MQTT specification, there is "Clear Session" option, the code uses Quality of Service (QoS) level 1 with clear session disabled. All your messages have use QoS1 to send, with client "Clear Session" set to FALSE when subscribe to the MQTT broker. For mobile phone app "IoT MQTT Panel", you need to uncheck the "Clear Session" option in "Additional options". 
- If you have QoS1 enabled with "Clear Session" enabled. Whenever there is a connection lost, all messages during the black out time will be lost.
- If you have QoS1 enabled with "Clear Session" disabled. All your messages will show up after reconnection.

In "mqtt_as", there are 2 settings, i.e. config["clean"] and config["clearn_init"]. The intention is to prevent large backlog of qos==1 messages being received if outage is long.
However, in this application, config["clean"] is set to False and config["clearn_init"] is set to True. 

# Important notes on Retain flag
In MQTT specification, a message can be published to MQTT broker on a Topic with a Retain flag. Please do not enable this flag on the client. The retain message will cause confusion.  For mobile phone app "IoT MQTT Panel", uncheck the "Retain" checkbox next to QoS1 settings.

# Important notes on Client ID
If you have multiple clients connecting to MQTT broker with the same Client ID, unexpected behavior can happen. For example, you configured mobile app "IoT MQTT Panel" with clientID = "MyHomeClient" and PicoW is using the same clientID. Mobile app is able to publish the message, but PicoW subscription will fail on message call back. Please make sure each device or client have a unique ID.

# Can relay on/off be scheduled?
From a technical standpoint, it's feasible to integrate the scheduling code into the microcontroller. However, I believe that scheduling shouldn't be its primary function. The microcontroller's main responsibility should revolve around hardware control and reporting hardware status through MQTT. For scheduling tasks, a more suitable approach would be to develop an Azure Function using MQTT NET or utilize Amazon AWS Lambda. This is a sample project I am running it on Azure (it uses TimerTrigger with CRON expression):

https://github.com/DIY-able/MqttTimerFunction

# Starting up with weak WIFI or power outage reboot
When you power up the PicoW without Wi-Fi or without a stable connection, the 'mqtt_as' module quits and shuts down. This behavior, as explained by Peter Hinch, is intentional. However, in cases of a power outage where both the Wi-Fi router and PicoW lose power simultaneously, upon restoration of power, the PicoW might start up before the Wi-Fi network is fully available, resulting in it being unable to function properly. To address this issue, a workaround is to implement a retry loop to attempt to connect to Wi-Fi a specified number of times (determined by the 'wifi_max_wait' parameter in the configuration) before initializing the 'mqtt_as' module.

# WPA3 issue
If you have enabled the "WPA2/WPA3" transition settings on your router, PicoW may experience connectivity issues. Switching the settings back to "WPA2 only" resolves this issue.


# Installation for PicoW
1. Use Micropython bootloader RPI_PICO_W-20240105-v1.22.1.uf2 or latest version
2. Use Thonny to install the .uf2 on PicoW
3. Use Thonny > Tools > Manage Package > "micropython-umqtt.simple" (Don't install simple2, robust, or robust2) on root, it should have the /lib folder
4. Upload all *.py files to ROOT of PicoW (NOTE: main.py is for PicoW autostart when USB is plugged in)
5. Modify the config values in mqtt_tiny_controller_config.py such as WiFi ssid/password, Mqtt topic/clientid/broker and the following:
   
       gpio_pins_for_relay_switch = {16, 17}            List of GPIO IDs regular relay switches
       gpio_pins_for_momentary_relay_switch = {18, 19}  List of GPIO IDs relay switches and configure them as momentary switches
       gpio_pins_for_contact_switch = {0, 1, 2, 3}      List of GPIO IDs for Normally Open (NO) contact switches e.g. magnetic contact 
7. Run main.py in Thonny for debugging or exit Thonny then plug PicoW in any USB outlet for auto start

# Usage by Example

- GP16, GP17 are defined as Relay
- GP18, GP19 are defined as Momentary Relay
- GP0, GP1, GP2, GP3 are defined as Contact Switch
- Client is defined as any client (e.g. MQTT web client, MQTT CLI, mobile app (such as "IoT MQTT Panel")
- MQTT broker is defined as any MQTT broker (e.g. HiveHQ or Mosquitto)

### Action A: Client sends a JSON message {"GP16":1} to MQTT broker
- PicoW Hardware: GP16 relay is set to ON
-        Response: {"GP16": 1}
- The code sends the response to MQTT broker, all subscribers have the updated message with GP16=1

### Action B: Client sends a JSON message {"GP16":0} to MQTT broker
- PicoW Hardware: GP16 relay is set to OFF 
-        Response: {"GP16": 0}
- The code sends the response to MQTT broker, all subscribers have the updated message with GP16=0

### Action C: Client sends a JSON message {"GP18":1} to MQTT broker
- PicoW Hardware: Toggle GP18 momentary relay by first setting the relay GPIO18 to ON, after 2 seconds, set GPIO18 relay to OFF
-        Response: {"GP18": 0}
- The code sends the response to MQTT broker, all subscribers have the final status with GP18=0

### Action D: Contact switch GP1 is connected physically on the hardware GPIO board
-        Response: {"GP1": 1}
- The code sends the response to MQTT broker, all subscribers have the updated message with GP1=1

### Action E: Combined Action A and Action D in sequence very quickly
-        Response: {"GP1": 1, "GP16": 1}
- The code sends the response to MQTT broker, all subscribers have the updated message with GP1=1 and GP16=1

### Action F: First time running
-        Response: {"GP0": 0, "GP1": 0, "GP2": 0, "GP3": 0, "GP16": 0, "GP17": 0, "GP18": 0, "GP19": 0}
- The code sends the response to MQTT broker, all subscribers have the FULL list status

### Action G: Client sends a message {"CMD":"stats"} to MQTT broker
-        Response: Uptime=1 days 5 hrs, Outages=0, Mem=32.9%, Temp=18.6C/65.5F
- The code sends the response to MQTT broker, notifying subscribers the device is still up and running with stats

### Action I: Client sends a message {"CMD":"getip"} to MQTT broker
-        Response: {"IP": "20.114.152.56"}
- The code seneds the response to MQTT broker, publishing the public IP where your Microcontroller is running

### Action J: Client sends a message {"CMD":"refresh"} to MQTT broker
-        Response: {"GP0": 1, "GP1": 1, "GP2": 0, "GP3": 0, "GP16": 0, "GP17": 0, "GP18": 0, "GP19": 0}
- The code sends the response to MQTT broker, all subscribers have the FULL list status, in this example GP0=1 and GP1=1

# Mobile App "IoT MQTT Panel" Setup by Example

- GP16, GP17 are defined as Relay
- GP18, GP19 are defined as Momentary Relay
- GP0, GP1, GP2, GP3 are defined as Contact Switch
### Switch: (For Relay Switch) 
       Payload On: 1, Payload Off: 0
       "Payload is JSON Data" is Checked
       JsonPath for subscribe: $.GP16
       JSON pattern for publish: {"GP16": <payload>}
       Qos sets to 1
       Retain: unchecked
### Switch: (For Momentary Switch) 
       Exactly same as setting up Relay Switch, just replace GP16 with GP18
### LED Indicator: (For magentic contact)
       Payload On: 1,  Payload Off: 0
       "Payload is JSON Data" is Checked
       JsonPath for subscribe: $.GP1
       QoS sets to 1
### Button: (For Statistics)
       Name: Stats
       Payload: {"CMD":"stats"}
       Qos sets to 0
### Button: (For Getting IP address)
       Name: GetIP
       Payload: {"CMD":"getip"}
       Qos sets to 0
### Button: (For Refresh All GPIO)
       Name: Refresh All GPIO
       Payload: {"CMD":"refresh"}
       Qos sets to 0
