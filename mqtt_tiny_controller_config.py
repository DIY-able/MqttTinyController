# Wifi and Broker settings
wifi_ssid = "xxxxxxxxxxxxxxxxxxx"
wifi_pass = "yyyyyyyyyyyyyyyyyyyy"
wifi_max_retries = 30   # Max retries for first time starting up to connect Wifi after initial powered up
wifi_reset_delay_in_seconds = 600  # Sleep for 10 minutes (600 seconds) if wifi has permanently failed after wifi_max_retries
broker_server = "zzzzzzzzzzzzzzzzzzzzzzzzz.hivemq.cloud"
broker_user = "aaaaaaaa"
broker_pass = "bbbbbbbb"

# Mqtt and GPIO settings
mqtt_topic = "topicname/action1"
mqtt_client_id = b"uniqueclient1234"  # Do not remove b in front, it's to encode client_id to byte
mqtt_qos = 1  # Use QoS1 for auto message recovery
mqtt_retain = False # Always DO NOT use Retain message
mqtt_clean = False  # Set this to False (clear session) for reconnection to work Qos1 message recovery during outage
gpio_prefix = "GP"   # use it on JSON message as key (e.g. "GP15" = GPIO Pin 15)

# Safeguard to stop publishing forever (until hardware reset) if it publishes exceeding x times in y seconds
publish_counter_max = 20
publish_threshold_in_seconds = 10

# Safeguard to protect hardware from massive number of messages flooding the device after disconnect and then reconnect with QoS1
hardware_modified_cooldown_period_in_seconds = 2

# Safeguard to protect hardware from excessive x number of connections in y seconds, resets counter to 0 after y seconds
hardware_modified_max = 5
hardware_modified_threshold_in_seconds = 60
hardware_violation_max = 3  # Hardware PIN will stop changing value if it exceeded x number of violation, ref: GpioHardwareViolationCounter {}

# Publishing to broker with existing status even nothing changes
scheduled_publish_in_seconds = 7200  # broadcast every 120min, -1 disable scheduled publish

# Momentary Switch (turn relay it momentary switch)
momentary_switch_delay_in_seconds = 2

# Define the physical GPIO PIN number on the PicoW board
gpio_pins_for_relay_switch = {16, 17}           # {[GPIO ID]}: List of GPIO IDs regular relay switches
gpio_pins_for_momentary_relay_switch = {18, 19}  # {[GPIO ID]}: List of GPIO IDs relay switches and make them into momentary relay
gpio_pins_for_contact_switch = {0, 1, 2, 3}     # {[GPIO ID]}: List of GPIO IDs for Normally Open (NO) contact switches such as magnetic contact

# Additional features (commands in JSON:  e.g {"CMD": "stats"} to check device status)
command_prefix = "CMD"
commands = {"stats":1, "refresh":2, "getip":3}
json_ip_provider = "https://jsonip.com" # Returns device public IP address in JSON format

