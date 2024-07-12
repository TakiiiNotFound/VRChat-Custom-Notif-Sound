import os
import re
import vrchatapi
from vrchatapi.api import authentication_api
from vrchatapi.exceptions import UnauthorizedException
from vrchatapi.models.two_factor_auth_code import TwoFactorAuthCode
from vrchatapi.models.two_factor_email_code import TwoFactorEmailCode
from http.cookiejar import LWPCookieJar
import asyncio
import websockets
import pygame
import glob
from colorama import init, Fore, Style  # Import colorama for colored output
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume

# Initialize Colorama
init(autoreset=True)

# Initialize pygame audio
pygame.mixer.init()

# Audio file paths
MUSIC_FILE = "Audio/Music.wav"
JOIN_FILE = "Audio/Join.wav"
LEAVE_FILE = "Audio/Leave.wav"
LOGGED_FILE = "Audio/Logged.wav"
NOTIF_FILE = "Audio/Notif.wav"

# Global variables for managing volume control
vrchat_volume = 1.0  # Initial volume (100%)

def set_vrchat_volume(volume):
    sessions = AudioUtilities.GetAllSessions()
    for session in sessions:
        volume_interface = session._ctl.QueryInterface(ISimpleAudioVolume)
        if session.Process and session.Process.name() == "VRChat.exe":
            volume_interface.SetMasterVolume(volume, None)

def save_cookies(client: vrchatapi.ApiClient, filename: str):
    cookie_jar = LWPCookieJar(filename=filename)
    for cookie in client.rest_client.cookie_jar:
        cookie_jar.set_cookie(cookie)
    cookie_jar.save()

def load_cookies(client: vrchatapi.ApiClient, filename: str):
    cookie_jar = LWPCookieJar(filename=filename)
    try:
        cookie_jar.load()
    except FileNotFoundError:
        cookie_jar.save()
        return
    for cookie in cookie_jar:
        client.rest_client.cookie_jar.set_cookie(cookie)
        # Extract auth token from cookies
        if cookie.name == 'auth':
            return cookie.value.strip('"')  # Return auth token without surrounding quotes

def save_credentials(username: str, password: str):
    with open("user_auth.txt", "w") as f:
        f.write(f"{username}\n")
        f.write(f"{password}")

def load_credentials():
    try:
        with open("user_auth.txt", "r") as f:
            lines = f.readlines()
            username = lines[0].strip()
            password = lines[1].strip()
            return username, password
    except FileNotFoundError:
        return None, None

def play_effect(file_path):
    sound = pygame.mixer.Sound(file_path)
    sound.play()

async def connect_to_websocket(api_client: vrchatapi.ApiClient):
    auth_token = load_cookies(api_client, "./cookies.txt")
    if not auth_token:
        print("Auth token not found in cookies.")
        return

    uri = f"wss://pipeline.vrchat.cloud/?authToken={auth_token}"
    user_agent = "CustomNotifSounds/1.0 my@email.com"

    try:
        async with websockets.connect(uri, extra_headers={'User-Agent': user_agent}) as websocket:
            print(f"Connected to WebSocket")
            while True:
                message = await websocket.recv()
                if message.startswith('{"type":"notification"'):
                    print(f"{Fore.LIGHTBLUE_EX}[Notification] {Style.RESET_ALL}Received notification")
                    play_effect(NOTIF_FILE)
    except (websockets.ConnectionClosed, websockets.ConnectionClosedError, websockets.InvalidStatusCode) as e:
        print(f"Connection lost. Reconnecting in 5 seconds... Error: {e}")
        await asyncio.sleep(5)  # Wait before trying to reconnect

async def monitor_vrchat_logs(api_client: vrchatapi.ApiClient):
    vrchat_log_dir = find_vrchat_log_directory()
    if not vrchat_log_dir:
        print(f"VRChat log directory not found.")
        return

    # Regular expression patterns for events in logs
    patterns = {
        'Lifting black fade': re.compile(r".*Lifting black fade(.*)"),
        'OnLeftRoom': re.compile(r".*OnLeftRoom(.*)"),
        'OnPlayerJoined': re.compile(r".*OnPlayerJoined(.*)"),
        'OnPlayerLeft': re.compile(r".*OnPlayerLeft([^R].*)"),  # Exclude lines ending with 'Room'
        'Authenticated via': re.compile(r".*Authenticated via(.*)")
    }

    initial_files = set(glob.glob(os.path.join(vrchat_log_dir, "output_log_*.txt")))
    processed_files = set()
    latest_file = None

    while True:  # Infinite loop for continuous monitoring
        log_files = set(glob.glob(os.path.join(vrchat_log_dir, "output_log_*.txt")))
        new_files = log_files - initial_files - processed_files

        if new_files:
            latest_file = max(new_files, key=os.path.getmtime)

            # Set VRChat.exe volume to 0% and play background music
            set_vrchat_volume(0.0)
            pygame.mixer.music.load(MUSIC_FILE)
            pygame.mixer.music.play(-1)  # Loop indefinitely

            with open(latest_file, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(0, os.SEEK_END)  # Move to the end of the file

                while True:
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.25)  # Adjust scan frequency (4 times per second)
                        continue

                    matched_event = None
                    for event, pattern in patterns.items():
                        match = re.search(pattern, line)
                        if match:
                            matched_event = event
                            event_text = match.group(1).strip()
                            break

                    if matched_event:
                        if matched_event == 'Lifting black fade':
                            # Set VRChat.exe volume to 100% and stop background music
                            set_vrchat_volume(1.0)
                            pygame.mixer.music.stop()
                        elif matched_event == 'OnLeftRoom':
                            # Set VRChat.exe volume to 0% and play background music
                            set_vrchat_volume(0.0)
                            pygame.mixer.music.load(MUSIC_FILE)
                            pygame.mixer.music.play(-1)  # Loop indefinitely
                        elif matched_event == 'OnPlayerJoined':
                            print(f"{Fore.LIGHTGREEN_EX}[Join]{Style.RESET_ALL} {event_text}")
                            play_effect(JOIN_FILE)
                        elif matched_event == 'OnPlayerLeft':
                            print(f"{Fore.RED}[Left]{Style.RESET_ALL} {event_text}")
                            play_effect(LEAVE_FILE)
                        elif matched_event == 'Authenticated via':
                            print(f"{Fore.LIGHTBLUE_EX}[Logged]{Style.RESET_ALL} {event_text}")
                            play_effect(LOGGED_FILE)

            processed_files.add(latest_file)

        else:
            await asyncio.sleep(0.25)  # Adjust scan frequency (4 times per second)

def find_vrchat_log_directory():
    # Example: Adjust this function to find your VRChat log directory
    possible_paths = [
        os.path.expanduser("~/AppData/LocalLow/VRChat/VRChat/"),
        os.path.expanduser("~/Library/Application Support/VRChat/VRChat/")
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    return None

async def main():
    saved_username, saved_password = load_credentials()

    if saved_username and saved_password:
        print("Using saved credentials.")
        username = saved_username
        password = saved_password
    else:
        username = input("Enter your username: ")
        password = input("Enter your password: ")
        save_credentials(username, password)

    configuration = vrchatapi.Configuration(
        username=username,
        password=password,
        host="https://api.vrchat.cloud/api/1"
    )

    with vrchatapi.ApiClient(configuration) as api_client:
        api_client.user_agent = "CustomNotifSounds/1.0 my@email.com"
        load_cookies(api_client, "./cookies.txt")

        auth_api = authentication_api.AuthenticationApi(api_client)

        try:
            current_user = auth_api.get_current_user()
        except ValueError:
            auth_api.verify2_fa_email_code(TwoFactorEmailCode(input("Email 2FA Code: ")))
            current_user = auth_api.get_current_user()
            save_cookies(api_client, "./cookies.txt")
        except UnauthorizedException as e:
            print(e)
            if e.status == 200:
                if "Email 2 Factor Authentication" in e.reason:
                    auth_api.verify2_fa_email_code(TwoFactorEmailCode(input("Email 2FA Code: ")))
                elif "2 Factor Authentication" in e.reason:
                    auth_api.verify2_fa(TwoFactorAuthCode(input("2FA Code: ")))
                current_user = auth_api.get_current_user()
                save_cookies(api_client, "./cookies.txt")
            else:
                print(f"Exception when calling API: {e}")
        except vrchatapi.ApiException as e:
            print(f"Exception when calling API: {e}")

        print("Logged in as:", current_user.display_name)

        tasks = [
            asyncio.create_task(connect_to_websocket(api_client)),
            asyncio.create_task(monitor_vrchat_logs(api_client))
        ]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
