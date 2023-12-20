'''
*
* PROJET : KaspaPriceBot
* AUTEUR : Arnaud 
* VERSIONS : 1.0.0
* NOTES : None
*
'''
import os
import pandas as pd
import asyncio
# Replace this import
import discord
# With this import
from discord.ext import commands, tasks
import datetime
import aiohttp
import configparser
import json

# Configuration and initialization
config = configparser.ConfigParser()
config.read('config.ini')
DISCORD_BOT_TOKEN = config['KEYS']['DISCORD_BOT_TOKEN']

# Initialize the intents variable
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True 

# Initialize 'bot' with 'intents'
bot = commands.Bot(command_prefix='!', intents=intents)

COINGECKO_URL_KAS = "https://api.coingecko.com/api/v3/simple/price?ids=kaspa&vs_currencies=usd"
CSV_FILENAME_KAS = "kas_data.csv"
PRICE_CHANGE_THRESHOLD_KAS = 0.05  # 5% for Kaspa

CURRENT_KAS_ATH = 0.154  # Replace with the current ATH of Kaspa
KAS_ATH_FILENAME = "kas_ath.csv"

LOG_FILE_NAME = "kaspapricebot.log"

def log_message(message: str):
    with open(LOG_FILE_NAME, "a") as log_file:
        log_file.write(f"{datetime.datetime.now()} - {message}\n")

'''ATH FOR KAS TOKEN'''
def initialize_kas_ath():
    global CURRENT_KAS_ATH
    try:
        df = pd.read_csv(KAS_ATH_FILENAME, sep=';', decimal=',')
        if not df.empty:
            CURRENT_KAS_ATH = df['ath_price'].iloc[-1]
    except FileNotFoundError:
        CURRENT_KAS_ATH = 0.154  # Your previously known ATH for Kaspa

# Make sure to call these initialization functions somewhere in your startup code
initialize_kas_ath()

'''FOR KASPA TOKEN'''

async def fetch_kas_price():
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(COINGECKO_URL_KAS) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if 'kaspa' in data and 'usd' in data['kaspa']:
                        price = data['kaspa']['usd']
                        log_message(f"KAS price retrieved from API: {price}")
                        return price
                    else:
                        log_message("Missing data in API response for KAS.")
                else:
                    log_message(f"API response error for KAS: Status {resp.status}")
        except aiohttp.ClientError as e:
            log_message(f"Connection error while fetching KAS price: {e}")
        return None

async def record_kas_price():
    price = await fetch_kas_price()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_data = {'time': now, 'price': price}

    if not os.path.exists(CSV_FILENAME_KAS):
        df = pd.DataFrame([new_data])
    else:
        df = pd.read_csv(CSV_FILENAME_KAS, sep=';', decimal=',')
        new_row = pd.DataFrame([new_data])
        # Supprimer les colonnes entièrement NA avant de concaténer
        new_row.dropna(axis=1, how='all', inplace=True)
        df.dropna(axis=1, how='all', inplace=True)
        df = pd.concat([df, new_row], ignore_index=True)

    df.to_csv(CSV_FILENAME_KAS, index=False, sep=';', decimal=',')

async def check_kas_price_change():
    global CURRENT_KAS_ATH

    if not os.path.exists(CSV_FILENAME_KAS) or os.path.getsize(CSV_FILENAME_KAS) == 0:
        log_message("CSV file for KAS does not exist or is empty.")
        return

    df = pd.read_csv(CSV_FILENAME_KAS, sep=';', decimal=',')
    if df.shape[0] < 2:
        log_message("Not enough KAS data to compare.")
        return

    latest_time = pd.to_datetime(df.iloc[-1]['time'])
    two_hours_ago = latest_time - pd.Timedelta(hours=2)
    df_within_two_hours = df[pd.to_datetime(df['time']) >= two_hours_ago]

    if df_within_two_hours.empty:
        log_message("Less than 2 hours of KAS data, taking the last two entries.")
        df_within_two_hours = df.tail(2)

    latest_price = df.iloc[-1]['price']

    # Check if the latest price surpasses the current ATH
    if latest_price > CURRENT_KAS_ATH:
        message = f"🚀 New ATH for KAS! Current price: ${latest_price} 🚀"
        CURRENT_KAS_ATH = latest_price
        await send_ath_alert(message, "KAS")
        record_new_kas_ath(latest_price)

    for index, row in df_within_two_hours.iterrows():
        old_price = row['price']
        change = (latest_price - old_price) / old_price
        if abs(change) >= PRICE_CHANGE_THRESHOLD_KAS:
            log_message(f"KAS: Significant price change of {change*100:.2f}% detected.")
            old_time = pd.to_datetime(row['time'])
            percentage_change = round(change * 100, 2)
            await send_kas_price_alert(latest_price, old_price, old_time, latest_time, percentage_change, "KAS")
            break

async def send_kas_price_alert(latest_price, old_price, old_time, latest_time, percentage_change):
    total_minutes_diff = int((latest_time - old_time).total_seconds() / 60)
    message = f"KAS: Price change of {percentage_change}% over {total_minutes_diff} min. New price: ${latest_price}, Old price: ${old_price}"
    try:
        with open('chat_ids.json', 'r') as file:
            chat_ids = json.load(file)
    except FileNotFoundError:
        log_message("chat_ids.json file for KAS not found. Creating a new file.")
        chat_ids = []
        with open('chat_ids.json', 'w') as file:
            json.dump(chat_ids, file)

    log_message(f"Chat IDs for KAS loaded from chat_ids.json file: {chat_ids}")

    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, content=message)
        except discord.Forbidden:
            log_message(f"The bot is blocked by user {chat_id} for KAS alerts.")
            continue
        except discord.HTTPException as e:
            log_message(f"HTTPException while sending KAS message to {chat_id}: {e}")
        except Exception as e:
            log_message(f"Unexpected error while sending KAS message to {chat_id}: {e}")

    # Update the CSV file for KAS
    log_message(f"Removing data from the kas csv except the latest price")
    new_data = {'time': latest_time.strftime('%Y-%m-%d %H:%M:%S'), 'price': latest_price}
    df_new = pd.DataFrame([new_data])
    df_new.to_csv(CSV_FILENAME_KAS, index=False, sep=';', decimal=',')

def record_new_kas_ath(ath_price):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_data = {'time': now, 'ath_price': ath_price}
    if not os.path.exists(KAS_ATH_FILENAME):
        df = pd.DataFrame([new_data])
    else:
        df = pd.read_csv(KAS_ATH_FILENAME, sep=';', decimal=',')
        new_row = pd.DataFrame([new_data])
        df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(KAS_ATH_FILENAME, index=False, sep=';', decimal=',')

'''MANAGE ATH ALERTS'''

# Modify the send_ath_alert function to handle both AVAX and BTC
async def send_ath_alert(message, token_type):
    chat_ids_file = 'chat_ids.json'

    try:
        with open(chat_ids_file, 'r') as file:
            chat_ids = json.load(file)
        # Send the message to each chat_id
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, content=message)
            except Exception as e:
                log_message(f"Error sending ATH alert for {token_type} to {chat_id}: {e}")  # No need to pass the file name anymore
    except FileNotFoundError:
        log_message(f"The file {chat_ids_file} was not found.")

'''GET PRICE FROM CSV ON COMMAND'''

def get_latest_price_from_csv(filename):
    if not os.path.exists(filename) or os.path.getsize(filename) == 0:
        log_message(f"No latest price in CSV for {filename}")
        return None  # Return None if the file doesn't exist or is empty
    df = pd.read_csv(filename, sep=';', decimal=',')
    latest_price = df.iloc[-1]['price']
    return latest_price

'''DISCORD COMMANDS'''

@bot.command()
async def kas(ctx):
    price = get_latest_price_from_csv(CSV_FILENAME_KAS)
    try:    
        if price is not None:
            log_message("Fetching KAS price through CSV")
            await ctx.send(f"The current price of KAS is ${price}")
        else:
            log_message("Fetching KAS price through API")
            price = await fetch_kas_price()  # Fallback to API if necessary
            await ctx.send(f"The current price of KAS is ${price}")
    except Exception as e:
        print(f"An error occurred: {e}")
        log_message(f"An error occurred: {e}")
    
@tasks.loop(minutes=1)
async def schedule_jobs():
    await record_kas_price()
    await check_kas_price_change()

@bot.event
async def on_ready():
    log_message(f'Logged in as {bot.user.name}')
    schedule_jobs.start()

if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)