'''
*
* PROJET : KaspaPriceBot
* AUTEUR : Arnaud 
* VERSIONS : 1.0.2
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
import sys

# Configuration and initialization
config = configparser.ConfigParser()
config.read('config.ini')
DISCORD_BOT_TOKEN = config['KEYS']['DISCORD_BOT_TOKEN']

# Utilisez script_dir pour définir le chemin du fichier discord_channels.json
script_dir = os.path.dirname(os.path.realpath(__file__))
os.chdir(script_dir)
config_path = os.path.join(script_dir, 'config.ini')
discord_channels_path = os.path.join(script_dir, 'discord_channels.json')

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
    
    log_message("Lecture des IDs de channel pour Discord...")

    if os.path.exists(discord_channels_path):
        with open(discord_channels_path, "r") as file:
            channels = json.load(file)
        
        for channel_id in channels:
            channel = bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(message)
                except discord.Forbidden:
                    # Évite de log si le bot a été bloqué par des utilisateurs...
                    continue 
                except discord.NotFound as e:
                    log_message(f"Erreur: Canal Discord {channel_id} non trouvé : {e}")
                except discord.HTTPException as e:
                    log_message(f"Erreur HTTP lors de l'envoi du message au canal Discord {channel_id}: {e}")
                except discord.InvalidArgument as e:
                    log_message(f"Erreur: Argument invalide pour le canal Discord {channel_id}: {e}")
                except Exception as e:
                    log_message(f"Erreur inattendue lors de l'envoi du message à Discord : {e}")
    else:
        log_message("Erreur: Le fichier discord_channels.json n'a pas été trouvé.")

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

async def send_ath_alert(message, token_type):
    log_message("Lecture des IDs de channel pour Discord...")

    if os.path.exists(discord_channels_path):
        with open(discord_channels_path, "r") as file:
            channels = json.load(file)
        
        for channel_id in channels:
            channel = bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(message)
                except discord.Forbidden:
                    continue
                except discord.NotFound as e:
                    log_message(f"Erreur: Canal Discord {channel_id} non trouvé : {e}")
                except discord.HTTPException as e:
                    log_message(f"Erreur HTTP lors de l'envoi du message au canal Discord {channel_id}: {e}")
                except discord.InvalidArgument as e:
                    log_message(f"Erreur: Argument invalide pour le canal Discord {channel_id}: {e}")
                except Exception as e:
                    log_message(f"Erreur inattendue lors de l'envoi du message à Discord : {e}")
    else:
        log_message("Erreur: Le fichier discord_channels.json n'a pas été trouvé.")

'''GET PRICE FROM CSV ON COMMAND'''

def get_latest_price_from_csv(filename):
    if not os.path.exists(filename) or os.path.getsize(filename) == 0:
        log_message(f"No latest price in CSV for {filename}")
        return None  # Return None if the file doesn't exist or is empty

    df = pd.read_csv(filename, sep=';', decimal=',')
    # Supprimer les lignes où 'price' est NaN
    df = df.dropna(subset=['price'])

    if df.empty:
        log_message(f"No valid price data in CSV for {filename}")
        return None

    latest_price = df.iloc[-1]['price']
    return latest_price

'''DISCORD COMMANDS'''

@bot.command()
async def startkas(ctx):
    try:
        log_message("startkas command received")
        if not os.path.exists(discord_channels_path):
            with open(discord_channels_path, "w") as file:
                json.dump([], file)
                
        with open(discord_channels_path, "r") as file:
            channels = json.load(file)

        if ctx.channel.id not in channels:
            channels.append(ctx.channel.id)
            with open(discord_channels_path, "w") as file:
                json.dump(channels, file)
            await ctx.send("This channel has been registered.")
            log_message(f"Channel {ctx.channel.id} has been registered.")
        else:
            await ctx.send("This channel is already registered.")
            log_message(f"Channel {ctx.channel.id} is already registered.")
    except FileNotFoundError:
        log_message("Error: The discord_channels.json file was not found or could not be created.")
    except Exception as e:
        log_message(f"Error executing !register: {e}")

@bot.command()
async def kas(ctx):
    try:
        with open(discord_channels_path, "r") as file:
            channels = json.load(file)

        if ctx.channel.id not in channels:
            await ctx.send("This channel is not registered. Please use the !startkas command to register this channel.")
            return

        price = get_latest_price_from_csv(CSV_FILENAME_KAS)
        if price is not None:
            log_message("Fetching KAS price through CSV")
            await ctx.send(f"The current price of KAS is ${price}")
        else:
            log_message("Fetching KAS price through API")
            price = await fetch_kas_price()  # Fallback to API if necessary
            await ctx.send(f"The current price of KAS is ${price}")
    except FileNotFoundError:
        await ctx.send("Error: The discord_channels.json file was not found or could not be created.")
        log_message("Error: The discord_channels.json file was not found or could not be created.")
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

@bot.event
async def on_error(event, *args, **kwargs):
    log_message(f"Erreur dans l'événement {event} : {sys.exc_info()[1]}")    

@bot.event
async def on_command_error(ctx, error):
    log_message(f"Erreur avec la commande {ctx.command}: {error}")    

if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)