import asyncio
import json
import os
import random
import re
import time
import traceback
from asyncio import create_task
from datetime import datetime, timedelta, timezone

import aiosqlite
import discord
from discord.ext import commands
from discord.ui import *
from dotenv import load_dotenv

import responses
import sheets

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
Text_ChannelID = 1268216583889621179
AUTH_USERS = os.getenv('SAMPLE_SPREADSHEET_ID')

# Enable intents
intents = discord.Intents.default()
intents.voice_states = True  # Enable the voice state intent
intents.guilds = True  # Enable the guilds intent (needed for voice channels)
intents.guild_messages = True
intents.guild_typing = True
intents.message_content = True

# Define your bot's prefix and pass in the intents 
bot = commands.Bot(command_prefix="%", intents=intents)

# Dictionary to store locks for specific users in specific sheets used for sign up sheet function
locks = {}
active_tasks={}

# Dictionary to keep track of users in voice channels
# voice_channel_users = {}
# user_joined_timedate = {}
# user_left_timedate = {}

# keeping track of channels and members
# members_dict = {}
# voice_channels = {}
# text_channels = {}
trackers = {} # {id: TrackerObject}
tracker = None
AUTH_TRACKERS = sheets.getauthusers()

# Global buffer to store members joining/leaving
# Dictionary to track the most recent action for each member
# member_status = {}  # {member: 1 for join, 0 for leave (after.channel, before.channel)}
# processing = False


# environment variabel for keeping track of the !trackme command
# global checkchannel
# global tracked
# global curtracker
# global trackerid
global curauthor
periodic_task = None
# global trackedlist
# global nick_track
# global keep_running

# trackerid = None                           # names and ids of the members that are in the channel that is being tracked
# nick_track = None                          # nick names of the members that are int he channel that is being tracked
curauthor = None                           # name of the member that has started the tracker
# curtracker = None                          # id of the member that has started the tracker
# tracked = False                            # boolean value for keeping track of the tracker function
# checkchannel = None                        # channel name should be a string
# trackedlist = set()                        # a set containing the members that are in the tracked channel
# keep_running = False                       # state in boolean to ensure that the periodic update keeps running until the track function is turned off
# update_lock = asyncio.Lock()               # lock for when the process of refreshing the mass list is happening to ensure there are no other processes happing at that time
# channel_update_lock = asyncio.Lock()       # Define a lock at the module level
# interval = 60                              # time for interval updates on the spread sheet for the mass list column
# last_event_time = time.time()              # time stamp capture for the last status update
# debounce_timer = None                      # debounce time capture for voicestate processes to ensure no processes would over lap
# pro_time = time.time()                     # time stamp capture for process_join_leave

# Check if the guild is allowed
async def is_guild_allowed(ctx):
    #print(str(ctx.guild) and str(ctx.guild.id) in os.getenv('AUTH_SERVERS'), "see the guild in question",str(ctx.guild) , str(ctx.guild.id), os.getenv('AUTH_SERVERS') )
    return str(ctx.guild) and str(ctx.guild.id) in os.getenv('AUTH_SERVERS')

# Reminder : only uncomment if you want the bot to leave the servers you dont have added to the white list.
# @bot.event
# async def on_guild_join(guild):
#     # Leave any guilds not in the whitelist
#     if str(guild.id) not in os.getenv('AUTH_SERVERS'):
#         await guild.leave()
#         print(f"Left guild {guild.name} (ID: {guild.id})")

@bot.check
async def global_check(ctx):
    # Prevent commands from running in disallowed guilds
    return await is_guild_allowed(ctx)

class Tracker:
    """
    Tracker class encapsulates the main state variables for tracking user activity,
    avoiding reliance on global variables and allowing better concurrency handling.
    """
    def __init__(self):
        self.tracked = False  # Flag indicating if tracking is active
        self.checkchannel = None  # Voice channel being monitored
        self.curtracker = None  # Current tracker (unused in provided code)
        self.trackerid = None  # ID of the user being tracked
        self.trackedlist = set()  # Set of tracked members in the voice channel
        self.keep_running = False  # Flag to control periodic update loop
        self.nick_track = None  # Stores members' nicknames for tracking
        self.processing = False  # Processing flag to avoid concurrent joins/leaves handling
        self.last_event_time = time.time()  # Last time an event occurred
        self.pro_time = time.time()  # Last time a periodic update occurred
        self.member_status = {}  # Dictionary to store member join/leave statuses
        self.semaphore = asyncio.Semaphore(6)  # Controls access to update Google Sheets concurrently
        self.debounce_timer = None                      # debounce time capture for voicestate processes to ensure no processes would over lap
        # Dictionary to keep track of users in voice channels
        self.voice_channel_users = {}
        self.user_joined_timedate = {}
        self.user_left_timedate = {}
        # keeping track of channels and members
        self.members_dict = {}
        self.voice_channels = {}
        self.rate_limit_interval = 1  # Minimum interval between Google Sheets updates
        self.last_update_time = time.time() - self.rate_limit_interval  # Last time Google Sheets was updated
        # Add lock protection around updates to tracker.member_status
        self.member_status_lock = asyncio.Lock()

    def get_member_status(self):
        return f"{self.member_status}"
    
    def get_curtracker(self):
        return f"{self.curtracker}"
    
    def get_trackedlist(self):
        return f"{self.trackedlist}"
    
    def get_checkchannel(self):
        return f"{self.checkchannel}"
    
    def get_trackerid(self):
        return f"{self.trackerid}"
    
    def get_user_joined_timedate(self):
        return f"{self.user_joined_timedate}"
    
    def get_user_left_timedate(self):
        return f"{self.user_left_timedate}"
    
    def update_last_event_time(self):
        """Updates the timestamp for the last event."""
        self.last_event_time = time.time()

    def update_last_call_time(self):
        """Updates the timestamp for the last api call ."""
        self.last_update_time = time.time()

    def should_rate_limit(self):
        """Checks if the rate limit interval has been met for Google Sheets update."""
        return time.time() - self.last_update_time < self.rate_limit_interval

    def should_check(self):
        """Checks if the rate limit interval has been met for Google Sheets update."""
        return time.time() - self.last_update_time > self.rate_limit_interval

# Instantiate the tracker object
# tracker = Tracker()

# Locks for controlling access to shared resources
update_lock = asyncio.Lock()
channel_update_lock = asyncio.Lock()

# Interval for periodic updates (in seconds)
interval = 60


# method for determinign to send a private message or a message in the channel being requested form

async def send_message(message, user_message, is_private):
    try:
        response = responses.handle_response(message)
        if is_private:
            await message.author.send(response)
        else:
            await message.channel.send(response)
        
    except Exception as e:
        print(f"Exception error:{print(traceback.format_exc())} {e}")


def run_bot():

    bot.run(BOT_TOKEN)
    


@bot.event
async def on_ready():
    # Run the setup database coroutine
    
    print(f'{bot.user} is now running worked')

@bot.event
async def on_message(message):

    global curauthor
    attachmessg = ""
    if message.author == bot.user:
        return
    
    username = str(message.author)
    user_message = str(message.content)
    channel = str(message.channel)
    curauthor = username

    # Check for attachments (e.g., uploaded images)
    if message.attachments:
        for attachment in message.attachments:
            if any(attachment.filename.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif']):
                print(f"Image or GIF detected: {attachment.url}")
                attachmessg += attachment.url + " "

    # Check for embeds (e.g., linked GIFs)
    if message.embeds:
        for embed in message.embeds:
            if embed.url and any(embed.url.endswith(ext) for ext in ['.gif']):
                print(f"GIF detected via embed: {embed.url}")
                attachmessg += embed.url + " "

    print(f"message {user_message} {attachmessg} from {username} in channel {channel}. Author ID is {message.author.id} and channel id is {message.channel.id}")

    # Check if the message is not empty before accessing the first character
    if user_message and user_message[0] == '*':
        
        await send_message(message, user_message, is_private=True)


    elif user_message and user_message[0] == '*':
        
        await send_message(message, user_message, is_private=False)

    await bot.process_commands(message) # Makes sure the bot will process commands other than chat commands.

#   Representation of the VC logs
#
#   user_left_timedate = {member1_id: time/date, member2_id: time/date, member3_id: time/date, member4_id: time/date}
#
#   user_join_timedate = {member1_id: time/date, member2_id: time/date, member3_id: time/date, member4_id: time/date}


@bot.event
async def on_voice_state_update(member, before, after):

    # Taking the current time in the UTC time
    current_time = get_date_time()


    print("event happened",before.channel, after.channel)

    if tracker and tracker.tracked and tracker.checkchannel:

        # Exit early if already processing to prevent interference
        # if tracker.processing:
        #     return
        
        # Update last_event_time for debounce handling
        tracker.last_event_time = time.time()
        await VCchekingtracker(member, before, after, current_time)

        print("in tracked check", tracker.tracked)
        async with tracker.member_status_lock:
            # Check if a user joined a voice channel
            if before.channel is None and after.channel is not None and str(after.channel.name) == str(tracker.checkchannel):
                print("joined channel")
                # Add or update to the dictionary with join state (1)
                tracker.member_status[member] = (1, (after, before))
                # Start processing the buffer after a short delay

            # Check if a user left a voice channel
            elif before.channel is not None and after.channel is None and str(before.channel.name) == str(tracker.checkchannel):
                print("left channel")
                # Add or update to the dictionary with leave state (0)
                
                tracker.member_status[member] = (0, (after, before))
                # Start processing the buffer after a short delay

            # Check if the user switched voice channels
            elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id and (str(before.channel.name) == str(tracker.checkchannel) or str(after.channel.name) == str(tracker.checkchannel)):
                # Consider the user both leaving the previous channel and joining the new one
                print("switched channel")
                if before.channel == tracker.checkchannel:
                    print("switched left")
                    tracker.member_status[member] = (0, (after, before))

                elif after.channel == tracker.checkchannel:
                    print("sitched joined")
                    tracker.member_status[member] = (1, (after, before))
        
        # trigger for processing events
        await debounce_process()  # Debounced trigger to process_joins_and_leaves
        # Start processing the buffer after a short delay
        # if len(member_status) > 0:
        #     print("member ststas size", member_status, len(member_status))
        #     await process_joins_and_leaves()


async def process_joins_and_leaves():
    
    if tracker and tracker.tracked:
        if tracker.processing:
            return  # If already processing, don't start a new batch
        
        # Swap member_status with a new empty dict for batch processing
        to_process = tracker.member_status
        tracker.member_status = {}

        # Calculate dynamic delay based on the time since the last event
        elapsed_time = time.time() - tracker.last_event_time
        total_wait = max(0, min(6, 6 - elapsed_time))  # Up to 6 seconds
        increment = 0.5  # Check every 1 second

        # Wait in smaller increments, checking for new events in each iteration
        while total_wait > 0:
            if tracker.member_status:  # Accumulate any new events that arrive during the wait
                print("new event", tracker.member_status, "at", get_date_time())
                async with tracker.member_status_lock:
                    to_process.update(tracker.member_status)
                    tracker.member_status.clear()
            
            await asyncio.sleep(min(increment, total_wait))  # Wait for the smaller of increment or remaining wait time
            total_wait -= increment  # Reduce the remaining wait time

        print("Completed wait period, now processing events:", to_process)
        if to_process:
            try:
                tracker.processing = True  # Mark processing as started
                print("Processing batch of joins/leaves...", to_process)
                
                joined_members = {(member.nick  if member.nick is not None else member.name): member.id for member, (status, info) in to_process.items() if status == 1} # gets members wit status 1 meaning that joined they vc.
                leave_members = {(member.nick if member.nick is not None else member.name): member.id for member, (status, info) in to_process.items() if status == 0} # gets the members with the status 0 meanin that they left the vc

                # Ensure only one operation can happen at a time
                async with channel_update_lock:
                    if joined_members:
                        join_channel = get_channel(1, to_process)
                        await get_members_in_channel(join_channel, joined_members)

                async with channel_update_lock:
                    if leave_members:
                        leave_channel = get_channel(0, to_process)
                        await remove_members_in_channel(leave_channel, leave_members)
                
            finally:
                # Clear the dictionary after processing
                to_process.clear()
                joined_members.clear()
                leave_members.clear()
                # Handle any new events that occurred during processing
                async with tracker.member_status_lock:
                    if tracker.member_status:
                        print("New events queued during batch processing:", tracker.member_status)
                        await process_joins_and_leaves()  # Process remaining events
                tracker.pro_time = time.time() # capturing the time stamp of the last process update.
                tracker.processing = False  # Mark processing as complete
                print("Batch processing complete and member_status cleared.")

def get_channel(check, to_process):
    if check ==1:
        # Gets the channel for a user that joins the checkedchannel , this channel will always be the after channel.
        channel  = next( after for member, (status, (after, before)) in to_process.items() if status == 1 and after.channel is not None and after.channel.name == tracker.checkchannel.name)

        if channel.channel.name != tracker.checkchannel.name:
            # exception for user that switches a channel, this means that the checkedchannel would be the before channel, because the channel is switched.
            channel = next(before for member, (status, (after, before)) in to_process.items() if status == 1 and before.channel is not None and before.channel.name == tracker.checkchannel.name)
    else:
        # Gets the channel for a user that leaves the checkedchannel , this channel will always be the before channel.
        channel = next(before for member, (status, (after, before)) in to_process.items() if status == 0 and before.channel is not None and before.channel.name == tracker.checkchannel.name)

        if channel.channel.name != tracker.checkchannel.name:
            # exception for user that switches a channel, this means that the checkedchannel would be the after channel, because the channel is switched.
            channel = next(after for member, (status, (after, before)) in to_process.items() if status == 0 and after.channel is not None and after.channel.name == tracker.checkchannel.name)
    
    return channel.channel


async def periodic_update(interval): # shoul only be ran when the track me function is called

    """
    Runs the updatepicklist function every `interval` seconds. 
    """
    firstiter = True

    while tracker.keep_running:
        if firstiter:
            await asyncio.sleep(interval) # Wait for `interval` to skip first loop.
            firstiter = False
            continue
        if (time.time() - tracker.pro_time) > 30: # if the process_join_leave had done an update less than 30s the periodic update would not update
                                            # updates will be made if more than 30s has elapsed , if not then the periodic update would continue waiting for its interval
            async with update_lock:  # Acquire lock for the update
                async with tracker.semaphore:  # Limits concurrent updates
                    if not tracker.should_rate_limit():  # Checks if rate limit allows the call
                            # If allowed, call the API update function
                            await asyncio.to_thread(sheets.updatepicklist, tracker.trackedlist, tracker.trackerid, True, {})  # Call the list update function
                            
                            # Update the last call time to reset the rate limit timer
                            tracker.update_last_call_time()
                    else:
                        while not tracker.should_check():
                            print(f"Rate limit exceeded, skipping update for: periodic update")
                            await asyncio.sleep(1)
                        if not tracker.should_rate_limit():  # Checks if rate limit allows the call
                                # If allowed, call the API update function
                                await asyncio.to_thread(sheets.updatepicklist, tracker.trackedlist, tracker.trackerid, True, {})  # Call the list update function
                                
                                # Update the last call time to reset the rate limit timer
                                tracker.update_last_call_time()
                                
                

                # Update pro_time to the current time after the update to reset the timer
                tracker.pro_time = time.time()
        else:

            await asyncio.sleep(interval)  # Wait for `interval` seconds


# Function to stop the loop
def stop_task():
    tracker.keep_running = False

async def updatesheet(members, todo, member_ids, memname):
    # Run the blocking function in a background thread
    await updatesheet_sync( members, todo, member_ids, memname)


# updates the sheet with the assigned call (add to or remove).
async def updatesheet_sync(members, todo, member_ids, memname):
    
    if todo:
        print("got all memebrs", members, tracker.trackerid)
        if len(members) > 0:
            #print("is the ", members, member_ids, user_joined_timedate )
            join_time_names = {name: tracker.user_joined_timedate[member_ids[name]] for name in members} # Extract the members that joined names paired with the time they joined
            #print("join times 1",join_time_names)
            async with tracker.semaphore:
                if not tracker.should_rate_limit():  # Checks if rate limit allows the call
                        # If allowed, call the API update function
                        await asyncio.to_thread(sheets.updatepicklist, list(tracker.trackedlist), tracker.trackerid, True, memname.keys()) # goes to sheets.updatepicklist to process and send API call to google sheets
                        
                        # Update the last call time to reset the rate limit timer
                        tracker.update_last_call_time()
                else:
                    while not tracker.should_check():
                        
                        print(f"Rate limit exceeded, skipping update for: updatepicklist new entry")
                        await asyncio.sleep(1)
                    if not tracker.should_rate_limit():  # Checks if rate limit allows the call
                            print("cheking")
                            # If allowed, call the API update function
                            await asyncio.to_thread(sheets.updatepicklist, list(tracker.trackedlist), tracker.trackerid, True, memname.keys()) # goes to sheets.updatepicklist to process and send API call to google sheets
                            
                            # Update the last call time to reset the rate limit timer
                            tracker.update_last_call_time()

            async with tracker.semaphore:
                if not tracker.should_rate_limit():  # Checks if rate limit allows the call
                        # If allowed, call the API update function
                        await asyncio.to_thread(sheets.updatepicklist, list(tracker.trackedlist), tracker.trackerid, True, memname.keys()) # goes to sheets.updatepicklist to process and send API call to google sheets
                        
                        # Update the last call time to reset the rate limit timer
                        tracker.update_last_call_time()
                else:
                    while not tracker.should_check():
                        print(f"Rate limit exceeded, skipping update for: addtosheet new entry")
                        await asyncio.sleep(1)
                    print("addnew check")
                    if not tracker.should_rate_limit():  # Checks if rate limit allows the call
                        # If allowed, call the API update function
                        await asyncio.to_thread(sheets.addtosheet, join_time_names, tracker.trackerid) #goes to sheets.addtosheet to process and to send API call to google sheets for updatin the sheet
                        
                        # Update the last call time to reset the rate limit timer
                        tracker.update_last_call_time()
                
    else:
        
        # Extract keys (names) from the dictionary to create a set
        res = set(memname.keys())

        # Extract the members that left names paired with the time they left
        left_time_names = {name: tracker.user_left_timedate[memname[name]] for name in res}

        # Extract the members that joined names paired with the time they joined
        jointime =  {name: tracker.user_joined_timedate[memname[name]] for name in res}
        #print("seein in left", members, member_ids, "res: ",res,"left time: ", left_time_names, "join time: ",jointime)

        # Removes the persons that left the vc form the tracklist
        tracker.trackedlist -= res

        async with tracker.semaphore:
            if not tracker.should_rate_limit():  # Checks if rate limit allows the call
                    # If allowed, call the API update function
                    await asyncio.to_thread(sheets.updatepicklist, list(tracker.trackedlist), tracker.trackerid, False, memname.keys()) # goes to sheets.updatepicklist to process and send API call to google sheets
                    
                    # Update the last call time to reset the rate limit timer
                    tracker.update_last_call_time()
            else:
                while not tracker.should_check():
                    print(f"Rate limit exceeded, skipping update for: updatepicklist old entries removing")
                    await asyncio.sleep(1)
                if not tracker.should_rate_limit():  # Checks if rate limit allows the call
                        # If allowed, call the API update function
                        await asyncio.to_thread(sheets.updatepicklist, list(tracker.trackedlist), tracker.trackerid, False, memname.keys()) # goes to sheets.updatepicklist to process and send API call to google sheets
                        
                        # Update the last call time to reset the rate limit timer
                        tracker.update_last_call_time()
            

        async with tracker.semaphore:
            if not tracker.should_rate_limit():  # Checks if rate limit allows the call
                    # If allowed, call the API update function
                    await asyncio.to_thread(sheets.updatepicklist, list(tracker.trackedlist), tracker.trackerid, False, memname.keys()) # goes to sheets.updatepicklist to process and send API call to google sheets
                    
                    # Update the last call time to reset the rate limit timer
                    tracker.update_last_call_time()
            else:
                while not tracker.should_check():
                    print(f"Rate limit exceeded, skipping update for: removeandupdate old entries removing")
                    await asyncio.sleep(1)
                if not tracker.should_rate_limit():  # Checks if rate limit allows the call
                        # If allowed, call the API update function
                        await asyncio.to_thread(sheets.remove_and_update_items, jointime, left_time_names, tracker.trackerid) # goes to sheets.remove_and_update_items to process and send API call to google sheets
                        
                        # Update the last call time to reset the rate limit timer
                        tracker.update_last_call_time()

async def get_members_in_channel(channel, memname):

    # Get all members in the specified voice channel and process their IDs.
    if channel is not None:
        members_in_channel = channel.members  # Get the list of all members in the voice channel
        
        tracker.nick_track = {(member.nick if member.nick is not None else member.name): member.id for member in members_in_channel} # Extract their ids
        #print(f"Members in {channel.name}: {member_nicks}")
        
        if len(tracker.trackedlist) == 0:
            member_nicks = [member.nick if member.nick is not None else member.name for member in members_in_channel] if members_in_channel else [] #[member.nick for member in members_in_channel]  # Extract their nicknames
            for i in member_nicks:
                if i is not None:
                    tracker.trackedlist.add(i)
            
            members = tracker.trackedlist
        else:
            
            # Extract keys (names) from the dictionary join_members
            members = set(memname.keys())

            print("seign the differneces", find_difference(members, tracker.trackedlist))
            
            # checks to see if members had tried to leave and join withing the batch period and are already in the tracked list.
            if find_difference(members, tracker.trackedlist):
                checked_members = find_difference(members, tracker.trackedlist)
            else:
                return # to not do anything beacuse the member/members are already on the sheet

            tracker.trackedlist.update(member for member in checked_members if member is not None and member not in tracker.trackedlist) # ensures that None value gets added to the tracked list (None values are commonly bots that are in the channel)
            print("tracked list:::", tracker.trackedlist)

        await updatesheet(members, True, tracker.nick_track, memname)  # Send member IDs to the process function
    else:
        print(f"Channel with ID {channel} not found.")


async def remove_members_in_channel(channel, memname):

    # Get all members in the specified voice channel and process their IDs.
    if channel is not None:
        members_in_channel = channel.members  # Get the list of all members in the voice channel
        member_nicks = [member.nick if member.nick is not None else member.name for member in members_in_channel] if members_in_channel else [] #[member.nick for member in members_in_channel]  # Extract their nicknames
        
        print(f"Members in {channel.name}: {member_nicks}")

        await updatesheet(member_nicks, False, tracker.nick_track, memname)  # Send member IDs to the process function
    else:
        print(f"Channel with ID {channel} not found.")


def is_allowed():
    async def predicate(ctx):
        id = re.sub("\D","",ctx.message.content)
        if id == "":
            await ctx.send("Error: Please enter a user to start tracking with `%trackme @username`.")
            return False
        if ctx.message.author.id == int(id):
            return True
        else:
            await ctx.send("Error:22 You can not start a tracker for a different user. You may not be authorized to use this command.")
            return False

    return commands.check(predicate)

def is_authtracker():
    async def predicate(ctx):
        
        if str(ctx.message.author.id) in AUTH_TRACKERS:
            return True
        else:
            await ctx.send(f'Error: You can not start a tracker for a different user. You may not be authorized to use this command.' )
            return False
    return commands.check(predicate)

@bot.command(name='trackme')
@is_allowed()
@is_authtracker()
async def find_user_voice(ctx, user_name: str):
    """Checks all voice channels for a specific user and returns the channel they are in."""
    global tracker
    curvoice_channels = ctx.guild.voice_channels
    found = False

    if tracker and tracker.tracked:
        await ctx.send(f"tracked is already being used to track {tracker.curtracker} voice channel in server {ctx.guild.name}")
    else:
        user_namec = re.sub("[<@>]","",user_name)
        
        for channel in curvoice_channels:
            members = channel.members
            for member in members:
                
                if str(member.id) == user_namec:
                    tracker = Tracker() # instantiate a tracker
                    await ctx.send(f'User "{user_name}" is in the voice channel: "{channel.name}"')
                    found = True
                    tracker.trackerid = user_namec
                    tracker.keep_running = True
                    tracker.checkchannel = channel
                    await checkVCs(tracker.checkchannel)
                    
                    # Start periodic update in the background (3 minutes = 180 seconds)
                    start_periodic_update(interval)
                    #bot.loop.create_task(periodic_update(interval))
                    # asyncio.create_task(periodic_update(interval))
                    tracker.tracked = True
                    members_in_vc = {(member.nick  if member.nick is not None else member.name): member.id for member in channel.members } # gets members in the tracked vc.
                    tracker.curtracker = tracker.members_dict[int(user_namec)]
                    async with channel_update_lock:
                        await get_members_in_channel(tracker.checkchannel, members_in_vc)
                    break  # Stop searching after finding the user

            if found:
                break  # Stop checking other channels if the user is found

        if not found:
            await ctx.send(f'User "{user_name}" is not currently in any voice channel.')

@find_user_voice.error
async def find_user_error(ctx, error):
    """Handles missing argument errors for the toggle_trigger command."""
    
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f'Error: You can not start a tracker for a different user. You may not be authorized to use this command.' )
    else:
        await ctx.send(f'Error: Please specify "off" `%trackoff` to toggle the tracker off and `%trackme @username` to toggle tracker on. Or you are not the current tracker {tracker.curtracker}' )

# check if members are in the members dictionary.
async def checkVCs(curvoice_channels):

    # taking the current time in the UTC time
    current_time = get_date_time()
    channel = curvoice_channels
    members = channel.members
    for member in members:
        
        if channel.id not in tracker.voice_channels:
            tracker.voice_channels[channel.id] = channel.name

        if channel.id not in tracker.voice_channel_users:
            tracker.voice_channel_users[channel.id] = []

        if member.id not in tracker.voice_channel_users[channel.id]:
            if member.id not in tracker.members_dict:
                tracker.members_dict[member.id] = member.name
            tracker.voice_channel_users[channel.id].append(member.id)
        
        if member.id not in tracker.user_joined_timedate and str(channel.name) == str(tracker.checkchannel):
            
            tracker.user_joined_timedate[member.id]= current_time
        if member.id in tracker.user_joined_timedate and str(channel.name) == str(tracker.checkchannel):
            
            tracker.user_joined_timedate[member.id]= current_time


# Track for date time Joined and left
async def VCchekingtracker(member, before, after, current_time):
        
        # Check if the user joined a voice channel
        if before.channel is None and after.channel is not None:
            channel = after.channel
            if channel.id not in tracker.voice_channels:
                tracker.voice_channels[channel.id] = channel.name
            if channel.id not in tracker.voice_channel_users:
                tracker.voice_channel_users[channel.id] = []
            if member.id not in tracker.voice_channel_users[channel.id]:
                if member.id not in tracker.members_dict:
                    tracker.members_dict[member.id] = member.name
                tracker.voice_channel_users[channel.id].append(member.id)
                print(f"{member.name} joined {channel.name} at {current_time}")
            # updating the VC logs
            
            if member.id not in tracker.user_joined_timedate and str(channel.name) == str(tracker.checkchannel):
                tracker.user_joined_timedate[member.id]= current_time
            if member.id in tracker.user_joined_timedate and str(channel.name) == str(tracker.checkchannel):
                tracker.user_joined_timedate[member.id]= current_time
        
        # Check if the user left a voice channel
        elif before.channel is not None and after.channel is None:
            channel = before.channel
            if channel.id in tracker.voice_channel_users:
                if member.id in tracker.voice_channel_users[channel.id]:
                    tracker.voice_channel_users[channel.id].remove(member.id)
                    print(f"{member.name} left {channel.name} at {current_time}")
                    
            if member.id not in tracker.user_left_timedate and str(channel.name) == str(tracker.checkchannel):
                tracker.user_left_timedate[member.id]= current_time
            if member.id in tracker.user_left_timedate and str(channel.name) == str(tracker.checkchannel):
                tracker.user_left_timedate[member.id]= current_time

        # Check if the user switched voice channels
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            # User left the previous channel
            if before.channel.id in tracker.voice_channel_users:
                if member.id in tracker.voice_channel_users[before.channel.id]:
                    tracker.voice_channel_users[before.channel.id].remove(member.id)
                    print(f"{member.name} left {before.channel.name} at {current_time}")
            channel = before.channel
            if member.id not in tracker.user_left_timedate and str(channel.name) == str(tracker.checkchannel):
                tracker.user_left_timedate[member.id]= current_time
            if member.id in tracker.user_left_timedate and str(channel.name) == str(tracker.checkchannel):
                tracker.user_left_timedate[member.id]= current_time
 
            # User joined the new channel
            
            if after.channel.id not in tracker.voice_channel_users:
                tracker.voice_channel_users[after.channel.id] = []

            if member.id not in tracker.voice_channel_users[after.channel.id]:
                tracker.voice_channel_users[after.channel.id].append(member.id)
                print(f"{member.name} joined {after.channel.name} at {current_time}")

            if after.channel.id not in tracker.voice_channels:
                    tracker.voice_channels[after.channel.id] = after.channel.name
            if member.id not in tracker.members_dict:
                tracker.members_dict[member.id] = member.name

            channel = after.channel
            if member.id not in tracker.user_joined_timedate and str(channel.name) == str(tracker.checkchannel):
                tracker.user_joined_timedate[member.id]= current_time
            if member.id in tracker.user_joined_timedate and str(channel.name) == str(tracker.checkchannel):
                tracker.user_joined_timedate[member.id]= current_time

def get_date_time():
    return datetime.now(timezone.utc).strftime("%y-%m-%d %H:%M:%S")

# finding different memebrs in two different lists.
def getdiffmembers(list1, list2):
    # Convert the lists to sets for fast comparison
    set1 = set(list1)
    set2 = set(list2)

    # Find names that are in list1 but not in list2 (difference)
    unique_to_list1 = set1 - set2

    # Find names that are in list2 but not in list1 (difference)
    unique_to_list2 = set2 - set1

    # Combine both differences to get all unique names
    all_unique_names = unique_to_list1.union(unique_to_list2)
    return all_unique_names

def find_difference(set1, set2):
    # Find elements in set1 that are not in set2
    difference = set1.difference(set2)
    
    # Return the difference if there are any, else return an empty set
    return difference if difference else set()

def is_tracker():
    async def predicate(ctx):
        return tracker.curtracker == curauthor
    return commands.check(predicate)

def start_periodic_update(interval):
    global periodic_task
    # Start the periodic update as an asyncio task
    periodic_task = asyncio.create_task(periodic_update(interval))
    print("Periodic update started.")

def stop_periodic_update():
    global periodic_task
    if periodic_task is not None:
        periodic_task.cancel()  # Cancel the task
        periodic_task = None
    else:
        print("No periodic update task to cancel.")

# Command to turn the tracking on or off
@bot.command(name="trackoff")
@is_tracker()
async def toggle_trigger(ctx):

    global tracker

    """Allows users to turn on or off the tracking of the voice channel."""

    print("turning off ... ")
    stop_task()
    stop_periodic_update()
    sheets.clear_columns(tracker.trackerid)
    del tracker
    tracker = None

    # Call the clear functions for clearing the lists and timers columns.
    await ctx.send("Voice channel tracking is now OFF.")


# Error handler for the 'toggle_trigger' command
@toggle_trigger.error
async def toggle_trigger_error(ctx, error):
    """Handles missing argument errors for the toggle_trigger command."""
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f'Error: Please specify "off" `%trackoff` to toggle the tracker off and `%trackme @username` to toggle tracker on. Or you are not the current tracker {tracker.curtracker}' )
    else:
        await ctx.send(f'Error: Please specify "off" `%trackoff` to toggle the tracker off and `%trackme @username` to toggle tracker on. Or you are not the current tracker {tracker.curtracker}' )

async def debounce_process():
    """
    Debounce function to handle join/leave events with an adaptive delay mechanism.
    If multiple events are detected within a short time, increases the debounce interval
    to smooth out bursts.
    """

    if tracker.debounce_timer:
        tracker.debounce_timer.cancel()  # Cancel the existing debounce task if there's a new event

    # Calculate adaptive delay based on the time since the last event
    adaptive_delay = max(1, 6 - (time.time() - tracker.last_event_time))

    # Schedule the debounced function to run after 1 second
    tracker.debounce_timer = asyncio.create_task(run_with_delay(process_joins_and_leaves, adaptive_delay))

async def run_with_delay(func, delay):
    await asyncio.sleep(delay)  # Wait for the debounce delay
    await func()  # Call the target function

def member_auth():
    async def predicate(ctx):
        # Convert the user ID to string for comparison
        if str(ctx.author.id) in AUTH_TRACKERS:
            return True
        else:
            # Send an error message and deny access
            await ctx.send(f"Error: You are not authorized to use this command , {ctx.author.mention}.")
            return False
    return commands.check(predicate)


@bot.event
async def on_command_error(ctx, error):
    """Handles errors for commands, including unknown commands."""
    
    # Check if the error is CommandNotFound (unknown command)
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"Error: Unknown command. Use `%help` to see available commands.")
    
    # Handle missing required arguments
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Error: Missing required argument. Check the command usage.")
    # Handle any other command error
    

@bot.command(name="getguildname")
async def find_guild_name(ctx):
    id = ctx.message.guild.id
    name = ctx.message.guild.name
    print(f'guild name is {name} and relating id is {id}.')

@bot.command(name="getmyname")
async def find_member_name(ctx):
    print('coundnt get name')
    id = ctx.message.author.id
    name = ctx.message.author.name
    nick = ctx.message.author.nick
    print(f'member name is {name} with the nickname {nick} and relating id is {id}.')

def shutdown():
    """Shuts down the bot."""
    print("Shutting down...")
    bot.close()


@bot.command(name="flip")
async def coinflip(ctx, guess: str):
    """Flips a coin and checks if the user's guess is correct."""
    guess = guess.lower()
    if guess not in ["heads", "tails"]:
        await ctx.send("Please choose either 'heads' or 'tails'. Example: `%flip heads`")
        return

    flip_result = random.choice(["heads", "tails"])

    if guess == flip_result:
        await ctx.send(f"🎉 You won! The coin landed on **{flip_result}**.")
    else:
        await ctx.send(f"😢 You lost. The coin landed on **{flip_result}**.")


#creating Select options for sign up sheet
# All roles needed :
#       Tanks: Golem, HOJ, Soul Scyte, Heavy Mace, Grailseeker, 1h Arcane, 1h Mace, Incubus, Icicle
#       Heals: Hallow Fall, Fallen
#       Support: Bedrock, Locus, Occult, Great Arcane, Oathkeeper, Rootbound
#       battlemount: Charriot, Basilisk, Eagle, Behemouth, Bastion, Balista, Ent
#       DPS: Realmbreaker, Lifecurse, Damnation, Permafrost, Spiked, Rift Glave, Dawnsong, Carving, Hellfire, Spirithunter


# Ensure the database and table are created
async def setup_database():
    async with aiosqlite.connect(os.getenv('DATABASE')) as db:
        await db.execute(f"""
        CREATE TABLE IF NOT EXISTS signup_sheets (
            sheet_id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            set_count TEXT NOT NULL,
            start_time_utc TEXT NOT NULL,
            location TEXT NOT NULL,
            ss_img TEXT NOT NULL,
            authnick TEXT NOT NULL
        )
        """)
        await db.execute(f"""
        CREATE TABLE IF NOT EXISTS signup_roles (
            sheet_id INTEGER NOT NULL,
            usernickname TEXT NOT NULL,
            role1 TEXT DEFAULT NULL,
            role2 TEXT DEFAULT NULL,
            role3 TEXT DEFAULT NULL,
            role4 TEXT DEFAULT NULL,
            FOREIGN KEY(sheet_id) REFERENCES signup_sheets(sheet_id),
            PRIMARY KEY (sheet_id, usernickname)
        )
        """)
        await db.commit()

def get_lock(sheet_id, usernickname):
    """Retrieve a unique lock for a specific sheet and user."""
    key = f"{sheet_id}:{usernickname}"
    if key not in locks:
        locks[key] = asyncio.Lock()
    return locks[key]

class SubroleDropdownView(discord.ui.View):
    embed_messages = {}  # Class-level dictionary to track embed messages by sheet_id

    def __init__(self, sheet_id: int, target_time_utc: str, member: str):
        super().__init__()
        self.sheet_id = sheet_id  # Store sheet_id
        self.role_data = {
            "Tank": ["Golem", "HOJ", "Soul Scythe", "Heavy Mace", "Grailseeker", "1h Arcane", "1h Mace", "Incubus", "Icicle", "Fill tank"],
            "DPS": ["Realmbreaker", "Lifecurse", "Damnation", "Permafrost", "Spiked", "Rift Glave", "Dawnsong", "Carving", "Hellfire", "Spirithunter", "Fill DPS"],
            "Healer": ["Hallow Fall", "Fallen", "Fill Healer"],
            "Support": ["Bedrock", "Locus", "Occult", "Great Arcane", "Oathkeeper", "Rootbound", "Fill Support"],
            "Battlemount": ["Chariot", "Basilisk", "Eagle", "Behemoth", "Bastion", "Ballista", "Ent", "Fill Battlemount"],
        }
        self.emot_list = {"Tank": "🛡️",
                    "DPS":"⚔️",
                    "Healer": "❤️‍🩹",
                    "Support":"🦾",
                    "Battlemount":"🏇"}
        
        self.role_type = ["Tank",
                    "DPS",
                    "Healer",
                    "Support",
                    "Battlemount"]

        self.target_time = datetime.strptime(target_time_utc, "%H:%M").replace(
            year=datetime.now(timezone.utc).year,
            month=datetime.now(timezone.utc).month,
            day=datetime.now(timezone.utc).day,
            tzinfo=timezone.utc,
        )
        self.task = None
        self.membernick = member
        self.followup_message = None  # Initialize the followup_message attribute

        if self.target_time <= datetime.now(timezone.utc):
            self.target_time += timedelta(days=1)  # Move to next day if time has passed

        for role_type, subroles in self.role_data.items():
            options = [discord.SelectOption(label=subrole, value=subrole) for subrole in subroles]
            # Add a category-specific 'None' option
            options.append(
                discord.SelectOption(
                    label=f"None {role_type}",
                    value=f"None {role_type}",
                    description=f"No role for {role_type} category"
                )
            )
            self.add_item(SubroleDropdown(sheet_id, role_type, self.role_data, options, placeholder=f"Select up to 2 {role_type} subroles"))

    @classmethod
    async def get_embed_message(cls, bot: discord.Client, sheet_id: int):
        """Retrieve the stored embed message using its sheet_id."""
        message_info = cls.embed_messages.get(sheet_id)
        if not message_info:
            return None  # Return None if the sheet_id is not in the dictionary
        try:
            channel = bot.get_channel(message_info["channel_id"]) or await bot.fetch_channel(message_info["channel_id"])
            return await channel.fetch_message(message_info["message_id"])
        except Exception as e:
            print(f"Failed to fetch message for sheet_id {print(traceback.format_exc())} {sheet_id}: {e}")
            return None
    
    @classmethod
    def save_embed_message(cls, sheet_id: int, message: discord.Message):
        """Save the embed message details using its sheet_id."""
        cls.embed_messages[sheet_id] = {
            "message_id": message.id,
            "channel_id": message.channel.id,
        }

    def start_task(self):
        """This method will start the timer task."""
        self.task = asyncio.create_task(self.start_timer())
        active_tasks[self.sheet_id] = self.task  # Add the task to the active_tasks dictionary

    async def start_timer(self):
        """Start the countdown timer and update the embed."""
        while True:
            now = datetime.now(timezone.utc)
            time_left = (self.target_time - now).total_seconds()

            if time_left > 0:
                #await asyncio.sleep(1)
                # update timer after 30sec
                if int(time_left) % 30 == 0:
                    embed_message = await self.get_embed_message(bot, self.sheet_id)
                    if embed_message:
                        await self.update_timer_only(bot)
                sleep_time = min(30, time_left)  # Reduce unnecessary wakeups
                await asyncio.sleep(sleep_time)
            else:
                if time_left <= 0:
                    # When the time is up, stop the task and process the sheet
                    await self.handle_time_up()
                    break

    async def send_or_edit_followup(self, interaction: discord.Interaction, content: str):
        if self.followup_message:
            try:
                # Edit the existing follow-up message
                await self.followup_message.edit(content=content)
                
            except discord.NotFound:
                # If the message no longer exists, send a new one
                self.followup_message = await interaction.followup.send(content=content, ephemeral=True,)
        else:
            # Send a new follow-up message
            self.followup_message = await interaction.followup.send(content=content,ephemeral=True,)

    def clone_embed(self, embed, time_str):
        """Helper function to clone an embed and modify the footer with the time remaining."""
        updated_embed = discord.Embed(
            title=embed.title,
            description=embed.description,
            color=embed.color
        )
        if embed.fields:
            for field in embed.fields:
                updated_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        if embed.author:
            updated_embed.set_author(name=embed.author.name, icon_url=embed.author.icon_url)
        if embed.footer:
            updated_embed.set_footer(text=f"⏳ Time Remaining: `{time_str}`")
        if embed.thumbnail:
            updated_embed.set_thumbnail(url=embed.thumbnail.url)
        if embed.image:
            updated_embed.set_image(url=embed.image.url)
        
        return updated_embed
    
    async def handle_time_up(self):
        """Handle actions when the timer reaches 0."""
        try:
            for child in self.children:
                if isinstance(child, discord.ui.Select):
                    child.disabled = True

            embed_message = await self.get_embed_message(bot, self.sheet_id)
            if embed_message:
                await self.finalize_signup_sheet(bot)
            
            # Fetch data from the database
            async with aiosqlite.connect(os.getenv('DATABASE')) as db:
                cursor = await db.execute("SELECT channel_id, author, content, set_count, start_time_utc, location, ss_img, authnick FROM signup_sheets WHERE sheet_id = ?", (self.sheet_id,))
                row_info = await cursor.fetchone()

            if str(row_info[1]) in sheets.SPREADSHEET_ID_dct:
                # Fetch signup roles data from the database
                async with aiosqlite.connect(os.getenv("DATABASE")) as db:
                    cursor = await db.execute("SELECT usernickname, role1, role2, role3, role4 FROM signup_roles WHERE sheet_id = ?", (self.sheet_id,))
                    signup_data = await cursor.fetchall()

                # Write signup data to the Google Sheet
                values = []
                for row in signup_data:
                    usernickname, *roles = row
                    # Add a blank cell for the checkbox and the nickname and roles
                    values.append([""] + [usernickname] + roles)
                
                # Update the Google Sheet
                sheets.signup_sheet(str(row_info[1]), self.sheet_id, values)

                # Clean up the database after updating the Google Sheet
                async with aiosqlite.connect(os.getenv("DATABASE")) as db:
                    await db.execute("DELETE FROM signup_roles WHERE sheet_id = ?", (self.sheet_id,))
                    await db.execute("DELETE FROM signup_sheets WHERE sheet_id = ?", (self.sheet_id,))
                    await db.commit()

                print(f"Successfully processed signup sheet for sheet ID (Update Google Sheet): {self.sheet_id}")
            else:
                # Clean up the database after time is up (if no Google Sheet update is required)
                async with aiosqlite.connect(os.getenv("DATABASE")) as db:
                    await db.execute("DELETE FROM signup_roles WHERE sheet_id = ?", (self.sheet_id,))
                    await db.execute("DELETE FROM signup_sheets WHERE sheet_id = ?", (self.sheet_id,))
                    await db.commit()

                print(f"Successfully processed signup sheet for sheet ID (No Google Sheet to update for {str(row_info[7])}): {self.sheet_id}")
        except Exception as e:
            print(f"❌ Error finalizing signup sheet {print(traceback.format_exc())} {self.sheet_id}: {e}")

        finally:
            # Remove the task from active_tasks and clean up
            if self.sheet_id in active_tasks:
                task = active_tasks.pop(self.sheet_id, None) # pops the active sheet id if it is actually in the dict
                if task:
                    task.cancel() # Cancel the running task
                    try:
                        await task
                    except asyncio.CancelledError:
                        print(f"Task for sheet {self.sheet_id} cancelled successfully.")

    async def finalize_signup_sheet(self, bot: discord.Client):
        """
        Finalizes the signup sheet by removing dropdowns and updating the embed 
        to indicate the signup period has ended.
        """
        try:
            # Get the current message containing the embed
            message = await self.get_embed_message(bot, self.sheet_id)
            if not message:
                print(f"No embed message found for sheet_id: {self.sheet_id}")
                return

            # Retrieve the existing embed
            embed = message.embeds[0] if message.embeds else None
            if embed:
                now = datetime.now(timezone.utc)
                time_left = (self.target_time - now).total_seconds()
                time_str = f"{int(time_left // 3600):02}:{int((time_left % 3600) // 60):02}:{int(time_left % 60):02}" if time_left > 0 else "Mass has started!"
                # Clone and modify the embed
                updated_embed = self.clone_embed(embed, time_str)
                updated_embed.clear_fields()  # Remove fields (optional, if desired)
                updated_embed.add_field(
                    name="⏰ Signup Ended",
                    value="The signup period has ended. Mass has started!",
                    inline=False,
                )
                updated_embed.set_footer(text="📅 Thank you for signing up!")

                # Lock editing to prevent race conditions
                lock = get_lock(self.sheet_id, "edit")
                async with lock:
                    # Update the message without any view (removes dropdowns)
                    await message.edit(embed=updated_embed, view=None)

            print(f"Signup sheet finalized for sheet_id: {self.sheet_id}")
        except discord.Forbidden:
            print(f"Bot lacks permissions to edit message for sheet_id {self.sheet_id}.")
        except discord.HTTPException as e:
            print(f"HTTP exception occurred while editing message: {e}")
        except Exception as e:
            print(f"Unexpected error while finalizing signup sheet: {traceback.format_exc()}")

    async def update_timer_only(self, bot: discord.Client):
            """Update only the timer portion of the embed without affecting dropdowns."""
            try:
                print("in timer only")
                message = await self.get_embed_message(bot, self.sheet_id)
                if not message:
                    print(f"in update timer No embed message found for sheet_id: {self.sheet_id}")
                    return

                embed = message.embeds[0] if message.embeds else None
                print("see embed", embed)
                if embed:
                    now = datetime.now(timezone.utc)
                    time_left = (self.target_time - now).total_seconds()
                    time_str = f"{int(time_left // 3600):02}:{int((time_left % 3600) // 60):02}:{int(time_left % 60):02}" if time_left > 0 else "Mass has started!"

                    # Clone and modify the embed using the helper function
                    updated_embed = self.clone_embed(embed, time_str)

                    # Lock editing to prevent race conditions
                    lock = get_lock(self.sheet_id, "edit")
                    async with lock:
                        await message.edit(embed=updated_embed, view=self)
                        
                    #await message.edit(embed=updated_embed) # Update the embed without affecting dropdowns
                    print(f"updated timer only")
            except discord.Forbidden:
                print(f"Bot lacks permissions to edit message for sheet_id  {print(traceback.format_exc())} {self.sheet_id}.")
            except discord.HTTPException as e:
                print(f"HTTP exception occurred while editing message:  {print(traceback.format_exc())} {e}")
            except Exception as e:
                print(f"Unexpected error updating timer: {print(traceback.format_exc())} {e}")

    async def update_embed(self, bot: discord.Client, interaction):
        """Update the entire embed with new data."""
        
        # if not message:
        #     print(f"in update embeded No embed message found for sheet_id: {self.sheet_id}")
        #     return
        try:
            message = await self.get_embed_message(bot, self.sheet_id)
            if not message:
                print(f"No embed message found for sheet_id check: {self.sheet_id}")

            time_left = (self.target_time - datetime.now(timezone.utc)).total_seconds()
            if time_left > 0:
                """Update the embed message to reflect the current database state."""
                async with aiosqlite.connect(os.getenv('DATABASE')) as db:
                    cursor = await db.execute("""
                        SELECT usernickname, role1, role2, role3, role4
                        FROM signup_roles
                        WHERE sheet_id = ?
                    """, (self.sheet_id,))
                    rows = await cursor.fetchall()

                # Group signups by main role category
                role_signups = {role: [] for role in self.role_data.keys()}
                
                for row in rows:
                    #print("the roles", row, rows)
                    username = row[0]
                    roles = [role for role in row[1::] if role]

                    # sorts the roles with there main category
                    sorted_roles = {key: [item for item in value if item in roles] for key, value in self.role_data.items()}

                    # Adds the member name and sub roles for each main role/ category
                    for category, subroles in sorted_roles.items():
                        if subroles:
                            role_signups[category].append(f"{username}: {subroles}")

                # Calculate remaining time
                now = datetime.now(timezone.utc)
                time_left = (self.target_time - now).total_seconds()
                time_str = f"{int(time_left // 3600):02}:{int((time_left % 3600) // 60):02}:{int(time_left % 60):02}" if time_left > 0 else "Mass has started!"

                async with aiosqlite.connect(os.getenv('DATABASE')) as db:
                    cursor = await db.execute("""
                        SELECT channel_id, author, content, set_count, start_time_utc, location, ss_img, authnick
                        FROM signup_sheets
                        WHERE sheet_id = ?
                    """, (self.sheet_id,))
                    row_info = await cursor.fetchall()
                    rows_info = row_info[0]
                
                # Create the embed
                embed = discord.Embed(
                    title=(f"👑🍄 **Come and join** {str(rows_info[2])} with **{rows_info[7]}** 🍄👑"),
                    description=(f"Massing from **`{str(rows_info[5])}`** ammount of sets **`1 + {str(rows_info[3])}`**\n"
                                f"Startign Mass at **`{rows_info[4]}`** Current time UTC: **`{now}`**\n"
                                "Select subroles for each category below:\n"
                                "You can select up to **2 subroles** for each category. "
                                "Maximum of **4 subroles total** across all categories."
                    ),
                    color=discord.Color.green(),
                )
                
                embed.set_thumbnail(url="https://media.discordapp.net/attachments/1044669830411862146/1304975286483292211/luigi_gang_shit.png?format=webp&quality=lossless")
                # Add the role columns and names with sub roles to the embeded message
                
                for column_title, members_list in process_roles_signup(role_signups, self.emot_list).items():
                    embed.add_field(
                        name=column_title,
                        value=members_list if members_list else "No signups yet.",
                        inline=True,
                    )

                # Add total signups and footer
                if rows_info[6] and rows_info[6].startswith("http"):
                    embed.set_image(url=rows_info[6])

                total_signups = len(set(row[0] for row in rows))
                embed.add_field(name="Total Signups", value=str(total_signups), inline=False)
                embed.set_footer(text=f"⏳ Time Remaining: `{time_str}`")

                if not message:
                    # Send a new embed if no existing message
                    if interaction.response.is_done():
                        sent_message = await interaction.followup.send(embed=embed, view=self)
                    else:
                        await interaction.response.send_message(embed=embed, view=self)
                        sent_message = await interaction.original_response()
                    # Save the new message in storage
                    self.save_embed_message(self.sheet_id, sent_message)
                else:
                    # Edit the existing message
                    # Lock editing to prevent race conditions
                    lock = get_lock(self.sheet_id, "edit")
                    async with lock:
                        await message.edit(embed=embed, view=self)
        except Exception as e:
            print(f"❌ Failed to update embed: {print(traceback.format_exc())} {e}")

def generate_role_message(updated_roles: list,role_data: dict,max_roles: int) -> str:
    #Generates a feedback message about the remaining roles and category breakdown.
    # Count remaining roles
    remaining_roles = max_roles - len([role for role in updated_roles if role and "None" not in role])
    # Breakdown by category
    role_breakdown = {category: 0 for category in role_data.keys()}
    for role in updated_roles:
        if role and "None" not in role:
            for category, subroles in role_data.items():
                if role in subroles:
                    role_breakdown[category] += 1
    # Create detailed feedback message
    breakdown_message = "\n".join(
        [f"**{category} roles:** {count}" for category, count in role_breakdown.items()]
    )
    role_list =str(updated_roles).replace("[", "").replace("]", "").replace("'", "")
    feedback_message = f"\n\nYou have **{remaining_roles} roles remaining** to choose. \n Roles selected are: `{role_list}` \n\n{breakdown_message}"
    return feedback_message

class SubroleDropdown(discord.ui.Select):

    def __init__(self, sheet_id: int, role_type: str, role_data:dict, options: list, placeholder: str):
        super().__init__(placeholder=placeholder, min_values=1, max_values=2, options=options)
        self.sheet_id = sheet_id
        self.role_type = role_type
        self.role_data = role_data
        
    """If you defer an interaction, you must ensure that no additional calls to
    interaction.response.send_message or similar methods are made directly. Instead, use
    interaction.followup.send() for subsequent messages."""
    
    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()  # Acknowledge the interaction without sending a response
            selected_options = self.values
            member = interaction.user
            max_roles_per_category = 2
            max_roles = 4

            #print("see hte values selected", selected_options, member)
            lock = get_lock(self.sheet_id, member.nick)
            async with lock:  # Prevent concurrent updates for the same user
                async with aiosqlite.connect(os.getenv('DATABASE')) as db:
                    # Fetch existing roles for the user
                    cursor = await db.execute(""" SELECT role1, role2, role3, role4 FROM signup_roles WHERE sheet_id = ? AND usernickname = ? """,(self.sheet_id, member.nick))
                    row = await cursor.fetchone()
                    #print("see wht ahte db has", row)
                    
                    # If no existing record, initialize with None
                    if not row:
                        # Insert a new row for the user if not exists
                        row = [None] * 4  # Columns for roles
                        await db.execute(f"""
                        INSERT INTO signup_roles (sheet_id, usernickname, role1, role2, role3, role4)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, (self.sheet_id, member.nick, *row))
                        await db.commit()

                    cursor = await db.execute("""
                        SELECT channel_id, author, content, set_count, start_time_utc, location, ss_img, authnick FROM signup_sheets WHERE sheet_id = ?
                    """, (self.sheet_id,))
                    sheet_info = await cursor.fetchall()

                    # Combine current roles and new selections, removing duplicates
                    # Filter out empty values (None) but keep the string 'None' explicitly
                    current_roles =  [role for role in row if role is not None]

                    # Handle category-specific 'None' selection finds and remove all roles if "None {category} was selected as an option"
                    category_none_value = f"None {self.role_type}"
                    if category_none_value in selected_options:
                        # Remove all roles for this category
                        updated_roles = [role if role not in self.role_data[self.role_type] else category_none_value for role in current_roles]
                        updated_roles += [None] * (max_roles - len(updated_roles))
                        message = f"You deselected all subroles for **{self.role_type}** from **`{sheet_info[0][7]}`** signup sheet."
                    else:
                        # Check if user exceeds max subroles
                        category_roles = [role for role in current_roles if role in self.role_data[self.role_type]]
                        selected_roles_count = len([role for role in selected_options if role not in category_roles])
                        if len(category_roles) + selected_roles_count > max_roles_per_category:
                            # User is exceeding the max subroles for this category
                            message = (f"You cannot select more than {max_roles_per_category} subroles for **{self.role_type}** "
                                    f"from **`{sheet_info[0][7]}`** signup sheet.\n"
                                    "To change your roles, deselect existing subroles for this category first.")
                            message += generate_role_message(current_roles, self.role_data, max_roles)
                            if isinstance(self.view, SubroleDropdownView):
                                await self.view.send_or_edit_followup(interaction, message)
                            return
                        # Check if user exceeds total roles across all categories
                        non_empty_roles = [role for role in current_roles if role and "None" not in role]

                        if len(non_empty_roles) + selected_roles_count > max_roles:
                            # User is exceeding the total max subroles across all categories
                            
                            message = (f"You cannot select more than {max_roles} subroles across all categories "
                                        f"from **`{sheet_info[0][7]}`** signup sheet.\n"
                                        "To change your roles, deselect existing subroles in other categories.")
                            message += generate_role_message(current_roles, self.role_data, max_roles)
                            if isinstance(self.view, SubroleDropdownView):
                                await self.view.send_or_edit_followup(interaction, message)
                            return
                    
                        # Update roles for this category
                        updated_roles = [role for role in current_roles if role not in self.role_data[self.role_type]]
                        updated_roles += [role for role in selected_options if role is not None]
                        updated_roles =[role for role in updated_roles if "None" not in role]
                        updated_roles = updated_roles[:max_roles]  # Enforce total role limit
                        updated_roles += [None] * (max_roles - len(updated_roles))
                        message = f"Your selections for **{self.role_type}** have been updated from **`{sheet_info[0][7]}`** signup sheet."

                    # Save updated roles
                    # Update database
                    await db.execute(f"""
                    UPDATE signup_roles
                    SET role1 = ?, role2 = ?, role3 = ?, role4 = ?
                    WHERE sheet_id = ? AND usernickname = ?
                    """, (*updated_roles, self.sheet_id, member.nick))
                    await db.commit()
                    # Append role details and total roles to the message
                    message += generate_role_message(updated_roles, self.role_data, max_roles)
            # Add a delay before refreshing the embed
            await asyncio.sleep(3)  # Give the user time to view the options

            # Update the embed with new data
            if isinstance(self.view, SubroleDropdownView):
                await self.view.update_embed(bot, interaction)
                await self.view.send_or_edit_followup(interaction, message)
            #await interaction.followup.send(content=message,ephemeral=True,)

        except Exception as e:
            print(f"Error in SubroleDropdown callback: {print(traceback.format_exc())} {e}")
            await interaction.followup.send(
                content="An error occurred while processing your selection. Please try again.",
                ephemeral=True,
            )
        #await print_all_members_with_roles()

def member_auth():
    async def predicate(ctx):
        # Convert the user ID to string for comparison
        if str(ctx.author.id) in AUTH_TRACKERS:
            return True
        else:
            # Send an error message and deny access
            await ctx.send(f"Error: You are not authorized to use this command , {ctx.author.mention}.")
            return False
    return commands.check(predicate)

# Command to send the dropdown menu
@bot.command(name='menu')
@member_auth()
async def signup(ctx):
    
    # Stores the questions that the bot will ask the user to answer in the channel that the command was made
    # Stores the answers for those questions in a different list
    signup_questions = ['Which channel will the signup sheet placed?', 'What is the content that is to be held?', 'How many sets are required? (e.g "2" meaning 1 + 2 sets)',
                         'Where is the mass location? ',f'What time in UTC will the mass start? (HH:MM) Current UTC time is `{get_date_time()}`', 
                         'Is there an image you would like to display for your sign up sheet? Valid files are "[.png, .jpg, .jpeg, .gif]" ']
    signup_answers = []
    messages_to_delete = []  # Track messages to delete

    # Checking to be sure the author is the one who answered and in which channel
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel
    
    # Askes the questions from the signup_questions list 1 by 1
    # Times out if the host doesn't answer within 30 seconds
    for question in signup_questions:
        sent_message = await ctx.send(question)
        messages_to_delete.append(sent_message)  # Track bot's question message

        try:
            message = await bot.wait_for('message', timeout= 30.0, check= check)
        except asyncio.TimeoutError:
            timeout_message =  await ctx.send('You didn\'t answer in time. Please try again and be sure to send your answer within 30 seconds of the question.')
            messages_to_delete.append(timeout_message)
            await asyncio.sleep(5)  # Give some time for the user to see the message
            await ctx.channel.delete_messages(messages_to_delete)  # Bulk delete messages
            return
        else:
            if question == 'Is there an image you would like to display for your sign up sheet? Valid files are "[.png, .jpg, .jpeg, .gif]" ':
                if message.content in ['No', 'N', 'n', 'no']:
                    signup_answers.append("No")
                    signup_answers.append("N")
                    messages_to_delete.append(message)
                else:
                    signup_answers.append(message.attachments)
                    signup_answers.append(message.embeds)
                    messages_to_delete.append(message)
            else:
                signup_answers.append(message.content)
                messages_to_delete.append(message)

    # Grabbing the channel id from the signup_questions list and formatting is properly
    # Displays an exception message if the host fails to mention the channel correctly
    try:
        c_id = int(signup_answers[0][2:-1])
        
        if not bot.get_channel(c_id):
            raise ValueError("Invalid channel ID")
    except:
        error_message =await ctx.send(f'You failed to mention the channel correctly. Please do it like this: {ctx.channel.mention} using the "#" identifier and select the channel.')
        messages_to_delete.append(error_message)  # Track error message
        await asyncio.sleep(5)  # Allow user to see the message
        await ctx.channel.delete_messages(messages_to_delete)
        return
    
    try:
        # Validate and parse the target time
        datetime.strptime(signup_answers[4], "%H:%M")
    except ValueError:
        error_message = await ctx.send("Invalid time format! Please provide the time in HH:MM (UTC).")
        messages_to_delete.append(error_message)
        await asyncio.sleep(5)
        await ctx.channel.delete_messages(messages_to_delete)

    attachmessg = None

    # Check for attachments (e.g., uploaded images)
    if signup_answers[5] != "No":
        if signup_answers[5]:  # Check for attachments
            for attachment in signup_answers[5]:
                if isinstance(attachment, discord.Attachment):  # Ensure it's an attachment
                    if any(attachment.filename.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif']):
                        print(f"Image or GIF detected: {attachment.url}")
                        attachmessg = attachment.url
                        break

        elif signup_answers[6]:  # Check for embeds
            for embed in signup_answers[6]:
                if isinstance(embed, discord.Embed) and embed.image:
                    if embed.image.url and any(embed.image.url.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif']):
                        print(f"Image detected via embed: {embed.image.url}")
                        attachmessg = embed.image.url
                        break
        else:
            error_message = await ctx.send(
                "Invalid file format! Please provide an image, GIF, or link to one, or type 'No' if you don't want to include an image."
            )
            messages_to_delete.append(error_message)
            await asyncio.sleep(5)
            await ctx.channel.delete_messages(messages_to_delete)
            return
    else:
        attachmessg = "No"

    if not str(signup_answers[2]).isnumeric():
        error_message = await ctx.send("Invalid answer given for the amount of sets that are required, this answer must be a numeric value. (e.g '2' meaning 1 + 2 sets) ")
        messages_to_delete.append(error_message)
        await asyncio.sleep(5)
        await ctx.channel.delete_messages(messages_to_delete)
        return

    async with aiosqlite.connect(os.getenv('DATABASE')) as db:
        await db.execute("""
            INSERT INTO signup_sheets (channel_id, author, content, set_count, start_time_utc, location, ss_img, authnick)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (c_id, str(message.author.id), str(signup_answers[1]), str(signup_answers[2]), str(signup_answers[4]), str(signup_answers[3]), str(attachmessg), str(message.author.nick),))
        await db.commit()

        # Fetch the sheet_id of the newly created signup sheet
        cursor = await db.execute("SELECT last_insert_rowid()")
        sheet_id = (await cursor.fetchone())[0]
    
    # Calculate time left
    now = datetime.now(timezone.utc)
    target_time = datetime.strptime(signup_answers[4], "%H:%M").replace( year=now.year, month=now.month, day=now.day, tzinfo=timezone.utc)
    time_left = (target_time - now).total_seconds()
    time_str = f"{int(time_left // 3600):02}:{int((time_left % 3600) // 60):02}:{int(time_left % 60):02}" if time_left > 0 else "Mass has started!"

    channel = bot.get_channel(c_id)

    if channel and sheet_id:
        embed = discord.Embed(
            title=f"👑🍄 **Come and join** {str(signup_answers[1])} with {message.author.nick} 🍄👑",
            description=(f"Massing from **`{str(signup_answers[3])}`** ammount of sets **`1 + {str(signup_answers[2])}`**\n"
                         f"Startign Mass at **`{signup_answers[4]}`** Current time UTC: **`{now}`**\n"
                "Select subroles for each category below:\n"
                "You can select up to **2 subroles** for each category. "
                "Maximum of **4 subroles total** across all categories."
                "🛡️ **Tank**\n"
                "⚔️ **DPS**\n"
                "❤️‍🩹 **Healer**\n"
                "🦾 **Support**\n"
                "🏇 **Battlemount**\n\n"
            ),
            color=discord.Color.green(),
        )
        
        embed.set_thumbnail(url="https://media.discordapp.net/attachments/1044669830411862146/1304975286483292211/luigi_gang_shit.png?format=webp&quality=lossless")
        if attachmessg and attachmessg.startswith("http"):
            embed.set_image(url=attachmessg)

        embed.set_footer( text=f"⏳ Time Remaining `{time_str}`")
        view = SubroleDropdownView(sheet_id, str(signup_answers[4]), message.author.nick)
        message = await channel.send(embed=embed, view=view)
        view.embed_message = message
        confirmation_message= await ctx.send(f"Sign up sheet made with ID: #{sheet_id} and sent to {channel}!!! 🥱👍")
        messages_to_delete.append(confirmation_message)  # Track confirmation message
        await asyncio.sleep(5)  # Allow some time for the user to see confirmation
        await ctx.channel.delete_messages(messages_to_delete)  # Bulk delete messages
        view.start_task()

@bot.command()
async def list_sheets(ctx):
    async with aiosqlite.connect(os.getenv('DATABASE')) as db:
        cursor = await db.execute("SELECT sheet_id, channel_id, author, content, set_count, start_time_utc, location, ss_img, authnick FROM signup_sheets")
        rows = await cursor.fetchall()

    if rows:
        embed = discord.Embed(
            title="📜 Active Signup Sheets",
            color=discord.Color.blue()
        )
        for row in rows:
            print("row", row)
            sheet_id, channel_id, author, content, set_count, start_time, location, ss_img, authnick = row
            embed.add_field(
                name=f"Sheet #{sheet_id}",
                value=f"**Content:** {content}\n**Start Time (UTC):** {start_time} \n **Author:** {authnick}",
                inline=False,
            )
        await ctx.send(embed=embed)
    else:
        await ctx.send("No active signup sheets.")


@bot.command()
async def cancel_sheet(ctx, sheet_id: int):
    #Cancel a specific signup sheet and remove its data from the database.

    async with aiosqlite.connect(os.getenv('DATABASE')) as db:
        # Check if the sheet exists
        cursor = await db.execute("SELECT * FROM signup_sheets WHERE sheet_id = ?", (sheet_id,))
        sheet = await cursor.fetchone()

        if not sheet:
            await ctx.send(f"❌ No signup sheet found with ID #{sheet_id}.")
            return

        # Delete associated roles
        await db.execute("DELETE FROM signup_roles WHERE sheet_id = ?", (sheet_id,))
        # Delete the signup sheet itself
        await db.execute("DELETE FROM signup_sheets WHERE sheet_id = ?", (sheet_id,))
        await db.commit()
        # Clear any cached data for the sheet
        if sheet_id in active_tasks:
            task = active_tasks.pop(sheet_id)  # Get the task and remove it from the active tasks dictionary
            task.cancel()  # Cancel the running task
        
    await ctx.send(f"✅ Signup sheet #{sheet_id} and all its associated data have been successfully canceled.")

# Function to break the members into smaller chunks of columns
def process_roles_signup(role_dict, emoji_map):
    max_length=1024
    processed_roles = {}

    for role_type, members in role_dict.items():
        emoji = emoji_map.get(role_type, '')
        part_counter = 1
        current_key = f"{emoji} {role_type}"
        current_part = []
        current_length = 0


        for member_str in members:
            # Clean the member string
            member_str = member_str.replace("[", "").replace("]", "").replace("'", "")
            member_length = len(member_str)

            # If adding this member exceeds the limit, save the current part and start a new one
            if current_length + member_length + 1 > max_length:  # +1 for newline
                processed_roles[current_key] = current_part
                # Start a new column (e.g., Tank Pt 2)
                part_counter += 1
                current_key = f"{emoji} {role_type} Pt {part_counter}"
                current_part = []
                current_length = 0

            # Add the member to the current part
            current_part.append(member_str)
            current_length += member_length + 1

        # Add any remaining part
        if current_part:
            processed_roles[current_key] = "\n".join(current_part)
    return processed_roles

