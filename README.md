# MqttTinyController
MqttTinyController runs on Raspberry Pi PicoW (RP2040) using any free cloud MQTT broker (e.g. HiveHQ or Mosquitto) to control home automation relay switches and contact switches. Support JSON payload for free mobile app such as "IoT MQTT Panel".

# Project
Many of the MQTT PicoW codes, samples, and tutorials available on the Internet lack the robustness required to handle real-life disasters. They often fall short, either being overly simplistic or lacking essential features. This code was crafted by just another average joe (me, a.k.a DIYable) who works as a software engineer full time with decades of experience in IT industry, yet it's first time to write Python. 

This code is designed to meet the demands of DIY enthusiasts, it has undergone extensive testing to ensure reliability, it's stable to run 24/7 at home. Capable of operating continuously without interruption, even in the face of potential threats such as hacking attempts targeting your MQTT client account to manipulate relay toggling and potentially starts a fire in your home, this solution offers a layer of protection. While the code may not be entirely bulletproof, your input and contributions for enhancement are greatly appreciated. Please feel free to share any improvements you identify to help advance this project.

# Features
- Support Relay (e.g. appliance control), Momentary Relay (e.g. garage door remote control, press/release) and contact switch (e.g. magnetic contact)
- Only one single MQTT Topic is needed for both publishers and subscribers with the use of JSON.
- Structure MQTT payload in JSON format to facilitate compatibility with mobile app "IoT MQTT Panel" leveraging JSON Path.
- Automatic WiFi reconnection functionality to seamlessly reconnect in case of disconnection.
- Automatic reconnection to the MQTT broker to maintain uninterrupted communication.
- Quality of Service (QoS) level 1 to guarantee no message loss even in the event of MQTT broker downtime or WiFi disconnection.
- Utilize the onboard LED to provide clear visual status indications: Operational, WiFi connection in progress, or System halted.
- Provide support for relay switches, with the added capability to configure them as momentary switches, ideal for controlling garage doors with press/release functionality on remote control.
- Support contact switches for status reporting, particularly useful for magnetic contact sensors.
- Implement hardware safeguards to prevent relay burnout caused by flooded incoming messages in a single batch, such as after WiFi reconnection.
- Integrate hardware safeguards to prevent relay burnout in scenarios of excessive toggling, automatically resuming operation after a predefined interval.
- Implement hardware safeguards to prevent message acceptance until a hardware reset if a predefined violation threshold is reached.
- Ensure data usage protection by halting MQTT message publishing in the event of a fatal error until a hardware reset is performed.
- Option to regularly publish hardware status to MQTT broker, broadcasting to all clients at predefined intervals for comprehensive monitoring and control.

# Hardware
- Raspberry Pi PicoW Pre-Soldered Header (e.g. Freenove FNK0065C from Amazon)
- 4Channel Relay Module (e.g. Sainsmart ‎101-70-101 from Amazon)
- Pico Breakout Board (e.g. Freenove FNK0081 from Amazon)

# Does the code work on ESP32 or Arduino Nano RP2040?
No idea. Maybe minor code changes is needed or maybe not.

# MQTT Library memory leak Fix
This project relies on the "micropython-umqtt.simple" library for its operation. However, navigating through its various versions like "umqtt.simple2," "umqtt.robust," or "umqtt.robust2" might lead to confusion. Unfortunately, all four libraries suffer from memory leaks or frozen issues if you are using the sample code from Internet. To illustrate, both "umqtt.simple" (with try/except reconnect) and "umqtt.robust" for auto-reconnect failed to pass my test cases on Raspberry Pi Pico W. While they managed to reconnect successfully, they persisted in experiencing memory leaks after several disconnect/reconnect cycles.  To validate this, use router firewall to block MQTT traffic and/or disconnect WIFI from router. Although they did reconnect successfully, it continued to have memory leak after several disconnect/reconnect. You can repeat the firewall block and WIFI disconnection for multiple times and use HiveMQ web client to publish messages after disconnect/reconnect. Eventually, it will lead to "out of memory" error:

       Traceback (most recent call last):
       File "<stdin>", line 47, in <module>
       OSError: [Errno 12] ENOMEM

or RTOS heap memory after reconnecting during SSL handshake

       Traceback (most recent call last):
       File "<stdin>", line 63, in <module>
       OSError: (-10368, 'MBEDTLS_ERR_X509_ALLOC_FAILED')

You can easily print out the memory usage and see it the memory usage keeps climbing. To fix robust, the library has to be modified. For this project, in order to keep it simple, I am using "micropython-umqtt.simple" library (no change to lib is needed) and apply auto re-connect on top. Memory leak was caused by repeatedly opening new connections without proper closure in an exception handling scenario. No memory leak issue is found in MqttTinyController project.

# Important notes on QoS1 with Clear Session
In MQTT specification, there is "Clear Session" option, the code uses Quality of Service (QoS) level 1 with clear session disabled. All your messages have use QoS1 to send, with client "Clear Session" set to FALSE when subscribe to the MQTT broker. For mobile phone app "IoT MQTT Panel", you need to uncheck the "Clear Session" option in "Additional options". 
- If you have QoS1 enabled with "Clear Session" enabled. Whenever there is a connection lost, all messages during the black out time will be lost.
- If you have QoS1 enabled with "Clear Session" disabled. All your messages will show up after reconnection.

# Important notes on Retain flag
In MQTT specification, a message can be published to MQTT broker on a Topic with a Retain flag. Please do not enable this flag on the client. The retain message will cause confusion.  For mobile phone app "IoT MQTT Panel", uncheck the "Retain" checkbox next to QoS1 settings.

# Important notes on ClientID
If you have multiple clients connecting to MQTT broker with the same ClientID, unexpected behavior can happen. For example, you configured mobile app "IoT MQTT Panel" with clientID = "MyHomeClient" and PicoW is using the same clientID. Mobile app is able to publish the message, but PicoW subscription will fail on message call back. 

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

- GP16 is defined as Relay
- GP18 is defined as Momentary Relay
- GP1 is defined as Contact Switch
- Client is defined as any client (e.g. MQTT web client, MQTT CLI, mobile app (such as "IoT MQTT Panel")
- MQTT broker is defined as any MQTT broker (e.g. HiveHQ or Mosquitto)

### Action A: Client sends a JSON message {"GP16":1} to MQTT broker
- PicoW Hardware: GP16 relay is set to ON
-        Response: {"GP0": 0, "GP1": 0, "GP2": 0, "GP3": 0, "GP16": 1, "GP17": 0, "GP18": 0, "GP19": 0}
- The code sends the response to MQTT broker, all subscribers have the updated message with GP16=1

### Action B: Client sends a JSON message {"GP16":0} to MQTT broker
- PicoW Hardware: GP16 relay is set to OFF 
-        Response: {"GP0": 0, "GP1": 0, "GP2": 0, "GP3": 0, "GP16": 0, "GP17": 0, "GP18": 0, "GP19": 0}
- The code sends the response to MQTT broker, all subscribers have the updated message with GP16=0

### Action C: Client sends a JSON message {"GP18":1} to MQTT broker
- PicoW Hardware: Toggle GP18 momentary relay by first setting the relay GPIO18 to ON, after 2 seconds, set GPIO18 relay to OFF
-        Response: {"GP0": 0, "GP1": 0, "GP2": 0, "GP3": 0, "GP16": 0, "GP17": 0, "GP18": 0, "GP19": 0}
- The code sends the response to MQTT broker, all subscribers have the final status with GP18=0

### Action D: Contact switch GP1 is connected physically on the hardware GPIO board
-        Response: {"GP0": 0, "GP1": 1, "GP2": 0, "GP3": 0, "GP16": 0, "GP17": 0, "GP18": 0, "GP19": 0}
- The code sends the response to MQTT broker, all subscribers have the updated message with GP1=1

### Action E: Combined Action A and Action D in sequence
-        Response: {"GP0": 0, "GP1": 1, "GP2": 0, "GP3": 0, "GP16": 1, "GP17": 0, "GP18": 0, "GP19": 0}
- The code sends the response to MQTT broker, all subscribers have the updated message with GP1=1 and GP16=1

# Mobile App "IoT MQTT Panel" Setup by Example
- GP16 is defined as Relay
- GP18 is defined as Momentary Relay
- GP1 is defined as Contact Switch
### Button: (For Relay Switch) 
       Payload On: 1, Payload Off: 0
       "Payload is JSON Data" is Checked
       JsonPath for subscribe: $.GP16
       JSON pattern for publish: {"GP16":<payload>}
       Qos sets to 1
       Retain: unchecked
### Button: (For Momentary Switch) 
       Exactly same as setting up Relay Switch, just replace GP16 with GP18
### LED Indicator: (For magentic contact)
       Payload On: 1,  Payload Off: 0
       "Payload is JSON Data" is Checked
       JsonPath for subscribe: $.GP1
       QoS sets to 1
