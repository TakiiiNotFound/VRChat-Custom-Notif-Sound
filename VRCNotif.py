import os
import re
import time
import vrchatapi
from vrchatapi.api import authentication_api, avatars_api
from vrchatapi.exceptions import UnauthorizedException, ApiException
from vrchatapi.models.two_factor_auth_code import TwoFactorAuthCode
from vrchatapi.models.two_factor_email_code import TwoFactorEmailCode
from http.cookiejar import LWPCookieJar
import json
import requests
import asyncio
import websockets
import pygame
import glob

# Initialize pygame audio
pygame.mixer.init()

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

def find_vrchat_log_directory():
    # Build VRChat log directory path
    user_profile = os.getenv('USERPROFILE')
    if user_profile:
        vrchat_log_dir = os.path.join(user_profile, "AppData", "LocalLow", "VRChat", "VRChat")
        return vrchat_log_dir
    else:
        return None

async def monitor_vrchat_logs():
    vrchat_log_dir = find_vrchat_log_directory()
    if not vrchat_log_dir:
        print("VRChat log directory not found.")
        return

    print(f"Monitoring VRChat log directory: {vrchat_log_dir}")

    # Regular expression patterns for events in logs
    patterns = {
        'OnConnected': re.compile(r".*OnConnected.*"),
        'OnPlayerJoined': re.compile(r".*OnPlayerJoined.*"),
        'OnPlayerLeft': re.compile(r".*OnPlayerLeft.*")
    }

    initial_files = set(glob.glob(os.path.join(vrchat_log_dir, "output_log_*.txt")))
    processed_files = set()
    latest_file = None

    no_new_file_count = 0

    while True:
        log_files = set(glob.glob(os.path.join(vrchat_log_dir, "output_log_*.txt")))
        new_files = log_files - initial_files - processed_files

        if new_files:
            latest_file = max(new_files, key=os.path.getmtime)
            print(f"New log file detected: {latest_file}")
            no_new_file_count = 0  # Reset the counter since we found a new file

            with open(latest_file, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(0, os.SEEK_END)  # Move to the end of the file

                while True:
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(1)
                        continue

                    for event, pattern in patterns.items():
                        if re.search(pattern, line):
                            print(f"Detected event '{event}' in log line: {line.strip()}")
                            play_audio(event)

            processed_files.add(latest_file)

        else:
            no_new_file_count += 1
            if no_new_file_count >= 10:
                print("No new log file detected after 10 scans. Stopping the scan.")
                break
            else:
                print(f"No new log file detected. Attempt {no_new_file_count}/10")

        await asyncio.sleep(10)  # Adjust the scan interval as needed

def play_audio(event):
    # Map events to corresponding audio files
    audio_files = {
        'OnConnected': "Audio/LoadedIn.wav",
        'OnPlayerJoined': "Audio/Join.wav",
        'OnPlayerLeft': "Audio/Leave.wav"
    }

    audio_file = audio_files.get(event)
    if audio_file:
        print(f"Playing audio for event '{event}'")
        pygame.mixer.music.load(audio_file)
        pygame.mixer.music.play()

async def connect_to_websocket():
    # Load auth token from cookies
    auth_token = load_cookies(api_client, "./cookies.txt")
    if auth_token:
        uri = f"wss://pipeline.vrchat.cloud/?authToken={auth_token}"
        user_agent = "CustomNotifSounds/1.0 my@email.com"

        async with websockets.connect(uri, extra_headers={'User-Agent': user_agent}) as websocket:
            print(f"Connected to WebSocket")

            while True:
                message = await websocket.recv()
                if message.startswith('{"type":"notification"'):
                    print(f"Received notification")
                    # Play audio notification
                    pygame.mixer.music.load("Audio/Notif.wav")
                    pygame.mixer.music.play()
                # Do nothing for messages that do not start with '{"type":"notification"'
    else:
        print("Auth token not found in cookies.")

async def main():
    # Start monitoring VRChat logs and WebSocket connection concurrently
    await asyncio.gather(
        monitor_vrchat_logs(),
        connect_to_websocket()
    )

if __name__ == "__main__":
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
            auth_api.verify2_fa_email_code(two_factor_email_code=TwoFactorEmailCode(input("Email 2FA Code: ")))
            current_user = auth_api.get_current_user()
            save_cookies(api_client, "./cookies.txt")
        except UnauthorizedException as e:
            print(e)
            if e.status == 200:
                if "Email 2 Factor Authentication" in e.reason:
                    auth_api.verify2_fa_email_code(two_factor_email_code=TwoFactorEmailCode(input("Email 2FA Code: ")))
                elif "2 Factor Authentication" in e.reason:
                    auth_api.verify2_fa(two_factor_auth_code=TwoFactorAuthCode(input("2FA Code: ")))
                current_user = auth_api.get_current_user()
                save_cookies(api_client, "./cookies.txt")
            else:
                print("Exception when calling API: %s\n", e)
        except vrchatapi.ApiException as e:
            print("Exception when calling API: %s\n", e)

        print("Logged in as:", current_user.display_name)

        # Run asyncio main loop for WebSocket connection and log monitoring
        asyncio.run(main())
