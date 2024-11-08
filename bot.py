import asyncio
import json
import os
import random
import re
import time
from asyncio import create_task
from datetime import datetime, timezone

import discord
from discord.ext import commands

import responses
import sheets

BOT_TOKEN = os.environ.get('BOT_TOKEN')
Text_ChannelID = 1268216583889621179
AUTH_USERS = os.environ.get('SAMPLE_SPREADSHEET_ID')

# Enable intents
intents = discord.Intents.default()
intents.voice_states = True  # Enable the voice state intent
intents.guilds = True  # Enable the guilds intent (needed for voice channels)
intents.guild_messages = True
intents.guild_typing = True
intents.message_content = True

# Define your bot's prefix and pass in the intents 
bot = commands.Bot(command_prefix="%", intents=intents)


# Dictionary to keep track of users in voice channels
voice_channel_users = {}
user_joined_timedate = {}
user_left_timedate = {}

# keeping track of channels and members
members_dict = {}
voice_channels = {}
text_channels = {}
AUTH_TRACKERS = sheets.getauthusers()

# Global buffer to store members joining/leaving
# Dictionary to track the most recent action for each member
member_status = {}  # {member: 1 for join, 0 for leave (after.channel, before.channel)}
processing = False


# environment variabel for keeping track of the !trackme command
global checkchannel
global tracked
global curtracker
global trackerid
global curauthor
global trackedlist
global nick_track
global keep_running

trackerid = None                           # names and ids of the members that are in the channel that is being tracked
nick_track = None                          # nick names of the members that are int he channel that is being tracked
curauthor = None                           # name of the member that has started the tracker
curtracker = None                          # id of the member that has started the tracker
tracked = False                            # boolean value for keeping track of the tracker function
checkchannel = None                        # channel name should be a string
trackedlist = set()                        # a set containing the members that are in the tracked channel
keep_running = False                       # state in boolean to ensure that the periodic update keeps running until the track function is turned off
update_lock = asyncio.Lock()               # lock for when the process of refreshing the mass list is happening to ensure there are no other processes happing at that time
channel_update_lock = asyncio.Lock()       # Define a lock at the module level
interval = 60                              # time for interval updates on the spread sheet for the mass list column
last_event_time = time.time()              # time stamp capture for the last status update
debounce_timer = None                      # debounce time capture for voicestate processes to ensure no processes would over lap
pro_time = time.time()                     # time stamp capture for process_join_leave

# method for determinign to send a private message or a message in the channel being requested form

async def send_message(message, user_message, is_private):
    try:
        response = responses.handle_response(message)
        if is_private:
            await message.author.send(response)
        else:
            await message.channel.send(response)
        
    except Exception as e:
        print("Exception error:", e)


def run_bot():

    @bot.event
    async def on_ready():
        print(f'{bot.user} is now running worked')


    @bot.event
    async def on_message(message):

        global curauthor

        if message.author == bot.user:
            return
        
        username = str(message.author)
        user_message = str(message.content)
        channel = str(message.channel)
        curauthor = username

        print(f"message {user_message} from {username} in channel {channel}. Author ID is {message.author.id} and channel id is {message.channel.id}")

        if user_message[0] == '*':
            user_message = user_message[1:]

            await send_message(message, user_message, is_private=True)

        elif user_message[0] == '!':

            await send_message(message, user_message, is_private=False)

        await bot.process_commands(message) # Makes sure the bot will process commands other than chat commands. 



    bot.run(BOT_TOKEN)


#   Representation of the VC logs
#
#   user_left_timedate = {member1_id: time/date, member2_id: time/date, member3_id: time/date, member4_id: time/date}
#
#   user_join_timedate = {member1_id: time/date, member2_id: time/date, member3_id: time/date, member4_id: time/date}


@bot.event
async def on_voice_state_update(member, before, after):
    global last_event_time

    # Taking the current time in the UTC time
    current_time = get_date_time()

    print("event happened",before.channel, after.channel)
    if tracked and checkchannel:

        # Exit early if already processing to prevent interference
        if processing:
            return
        
        # Update last_event_time for debounce handling
        last_event_time = time.time()
        await VCchekingtracker(member, before, after, current_time)

        await debounce_process()  # Debounced trigger to process_joins_and_leaves
        print("in tracked check", tracked)
        


        # Check if a user joined a voice channel
        if before.channel is None and after.channel is not None and str(after.channel.name) == str(checkchannel):
            print("joined channel")
            # Add or update to the dictionary with join state (1)
            member_status[member] = (1, (after, before))
            # Start processing the buffer after a short delay

        # Check if a user left a voice channel
        elif before.channel is not None and after.channel is None and str(before.channel.name) == str(checkchannel):
            print("left channel")
            # Add or update to the dictionary with leave state (0)
            member_status[member] = (0, (after, before))
            # Start processing the buffer after a short delay

        # Check if the user switched voice channels
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id and (str(before.channel.name) == str(checkchannel) or str(after.channel.name) == str(checkchannel)):
            # Consider the user both leaving the previous channel and joining the new one
            print("switched channel")
            if before.channel == checkchannel:
                print("switched left")
                member_status[member] = (0, (after, before))

            elif after.channel == checkchannel:
                print("sitched joined")
                member_status[member] = (1, (after, before))
            
        # Start processing the buffer after a short delay
        if len(member_status) > 0:
            print("member ststas size", member_status, len(member_status))
            await process_joins_and_leaves()

    
        # print(voice_channel_users)
        # print("test dict: ",user_joined_left_timedate)
        # print("members list:", members_dict)
        # print("Voice channels list: ", voice_channels)

async def process_joins_and_leaves():
    global processing, member_status, pro_time

    if tracked:
        if processing:
            return  # If already processing, don't start a new batch
        
        #async with update_lock:  # Only one coroutine can modify member_status
        

        # Swap member_status with a new empty dict for batch processing
        to_process = member_status
        member_status = {}

        # Calculate dynamic delay based on the time since the last event
        elapsed_time = time.time() - last_event_time
        total_wait = max(0, min(6, 6 - elapsed_time))  # Up to 6 seconds
        increment = 1  # Check every 1 second

        # Wait in smaller increments, checking for new events in each iteration
        while total_wait > 0:
            if member_status:  # Accumulate any new events that arrive during the wait
                to_process.update(member_status)
                member_status.clear()
            
            await asyncio.sleep(min(increment, total_wait))  # Wait for the smaller of increment or remaining wait time
            total_wait -= increment  # Reduce the remaining wait time

        print("Completed wait period, now processing events:", to_process)
        if to_process:
            try:
                processing = True  # Mark processing as started
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
                pro_time = time.time() # capturing the time stamp of the last process update.
                processing = False  # Mark processing as complete
                print("Batch processing complete and member_status cleared.")

def get_channel(check, to_process):
    if check ==1:
        # Gets the channel for a user that joins the checkedchannel , this channel will always be the after channel.
        channel  = next( after for member, (status, (after, before)) in to_process.items() if status == 1 and after.channel is not None and after.channel.name == checkchannel.name)

        if channel.channel.name != checkchannel.name:
            # exception for user that switches a channel, this means that the checkedchannel would be the before channel, because the channel is switched.
            channel = next(before for member, (status, (after, before)) in to_process.items() if status == 1 and before.channel is not None and before.channel.name == checkchannel.name)
    else:
        # Gets the channel for a user that leaves the checkedchannel , this channel will always be the before channel.
        channel = next(before for member, (status, (after, before)) in to_process.items() if status == 0 and before.channel is not None and before.channel.name == checkchannel.name)

        if channel.channel.name != checkchannel.name:
            # exception for user that switches a channel, this means that the checkedchannel would be the after channel, because the channel is switched.
            channel = next(after for member, (status, (after, before)) in to_process.items() if status == 0 and after.channel is not None and after.channel.name == checkchannel.name)
    
    return channel.channel


async def periodic_update(interval):
    global pro_time

    current_time = get_date_time()
    """
    Runs the updatepicklist function every `interval` seconds.
    """
    firstiter = True
    while keep_running:
        if firstiter:
            await asyncio.sleep(interval) # Wait for `interval` to skip first loop.
            firstiter = False
            continue
        if (time.time() - pro_time) > 30: # if the process_join_leave had done an update less than 30s the periodic update would not update
                                            # updates will be made if more than 30s has elapsed , if not then the periodic update would continue waiting for its interval
            async with update_lock:  # Acquire lock for the update

                sheets.updatepicklist(trackedlist, trackerid, True, 'somename')  # Call the list update function
                # Update pro_time to the current time after the update to reset the timer
                pro_time = time.time()
        else:

            await asyncio.sleep(interval)  # Wait for `interval` seconds


# Function to stop the loop
def stop_task():
    global keep_running
    keep_running = False

# updates the sheet with the assigned call (add to or remove).
async def updatesheet(members, todo, member_ids, memname):

    global trackedlist  # Keeps track of the persons in the vc

    # print("made it here", member_ids)
    
    if todo:
        print("got all memebrs", members)
        if len(members) > 0:
            #print("is the ", members, member_ids, user_joined_timedate )
            join_time_names = {name: user_joined_timedate[member_ids[name]] for name in members} # Extract the members that joined names paired with the time they joined
            #print("join times 1",join_time_names)
            sheets.updatepicklist(list(trackedlist), trackerid, True, memname.keys())
            sheets.addtosheet(join_time_names, trackerid)
                
            
    else:
        
        #res1 = trackedlist - set(members)
        # Extract keys (names) from the dictionary to create a set
        res = set(memname.keys())

        # Extract the members that left names paired with the time they left
        
        left_time_names = {name: user_left_timedate[memname[name]] for name in res}

        # Extract the members that joined names paired with the time they joined
        jointime =  {name: user_joined_timedate[memname[name]] for name in res}
        #print("seein in left", members, member_ids, "res: ",res,"left time: ", left_time_names, "join time: ",jointime)

        # Removes the persons that left the vc form the tracklist
        trackedlist -= res
        
        sheets.updatepicklist(list(trackedlist), trackerid, False, memname.keys())
        sheets.remove_and_update_items(jointime, left_time_names, trackerid)
            


async def get_members_in_channel(channel, memname):

    global nick_track
    global trackedlist  # Keeps track of the persons in the vc
    
    # Get all members in the specified voice channel and process their IDs.
    if channel is not None:
        members_in_channel = channel.members  # Get the list of all members in the voice channel
        
        nick_track = {(member.nick if member.nick is not None else member.name): member.id for member in members_in_channel} # Extract their ids
        #print(f"Members in {channel.name}: {member_nicks}")
        
        if len(trackedlist) == 0:
            member_nicks = [member.nick if member.nick is not None else member.name for member in members_in_channel] #[member.nick for member in members_in_channel]  # Extract their nicknames
            for i in member_nicks:
                if i is not None:
                    trackedlist.add(i)
            
            members = trackedlist
        else:
            
            # Extract keys (names) from the dictionary join_members
            members = set(memname.keys())

            #print("members with fntion", members1)
            print("members without fucntion", members)

            trackedlist.update(member for member in members if member is not None) # ensures that None value gets added to the tracked list (None values are commonly bots that are in the channel)
            print("tracked list:::", trackedlist)

        await updatesheet(members, True, nick_track, memname)  # Send member IDs to the process function
    else:
        print(f"Channel with ID {channel} not found.")


async def remove_members_in_channel(channel, memname):

    global nick_track

    # Get all members in the specified voice channel and process their IDs.
    if channel is not None:
        members_in_channel = channel.members  # Get the list of all members in the voice channel
        member_nicks = [member.nick if member.nick is not None else member.name for member in members_in_channel] #[member.nick for member in members_in_channel]  # Extract their nicknames
        
        print(f"Members in {channel.name}: {member_nicks}")

        await updatesheet(member_nicks, False, nick_track, memname)  # Send member IDs to the process function

        # After update inorder to update the nickname tracker
        #nick_track = {(member.nick if member.nick is not None else member.name): member.id for member in members_in_channel} # Extract their ids
        
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

    curvoice_channels = ctx.guild.voice_channels
    found = False

    # updateing the tracking values
    global tracked
    global checkchannel
    global curtracker
    global trackerid
    global keep_running

    if tracked:
        await ctx.send(f"tracked is already being used to track {curtracker} voice channel in server {ctx.guild.name}")
    else:
        
        
        user_namec = re.sub("[<@>]","",user_name)
        
        for channel in curvoice_channels:
            members = channel.members

            for member in members:
                
                if str(member.id) == user_namec:
                    await ctx.send(f'User "{user_name}" is in the voice channel: "{channel.name}"')
                    found = True
                    trackerid = user_namec
                    keep_running = True
                    checkchannel = channel
                    await checkVCs(checkchannel)

                    # Start periodic update in the background (3 minutes = 180 seconds)
                    bot.loop.create_task(periodic_update(interval))
                    # asyncio.create_task(periodic_update(interval))
                    tracked = True
                    members_in_vc = {(member.nick  if member.nick is not None else member.name): member.id for member in channel.members } # gets members in the tracked vc.
                    curtracker = members_dict[int(user_namec)]
                    async with channel_update_lock:
                        await get_members_in_channel(checkchannel, members_in_vc)
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
        await ctx.send(f'Error: Please specify "off" `%trackoff` to toggle the tracker off and `%trackme @username` to toggle tracker on. Or you are not the current tracker {curtracker}' )

# check if members are in the members dictionary.
async def checkVCs(curvoice_channels):

    # taking the current time in the UTC time
    current_time = get_date_time()
    channel = curvoice_channels
    members = channel.members
    for member in members:
        
        if channel.id not in voice_channels:
            voice_channels[channel.id] = channel.name

        if channel.id not in voice_channel_users:
            voice_channel_users[channel.id] = []

        if member.id not in voice_channel_users[channel.id]:
            if member.id not in members_dict:
                members_dict[member.id] = member.name
            voice_channel_users[channel.id].append(member.id)
        
        if member.id not in user_joined_timedate and str(channel.name) == str(checkchannel):
            
            user_joined_timedate[member.id]= current_time
        if member.id in user_joined_timedate and str(channel.name) == str(checkchannel):
            
            user_joined_timedate[member.id]= current_time


# Track for date time Joined and left
async def VCchekingtracker(member, before, after, current_time):
        
        # Check if the user joined a voice channel
        if before.channel is None and after.channel is not None:
            channel = after.channel
            if channel.id not in voice_channels:
                voice_channels[channel.id] = channel.name
            if channel.id not in voice_channel_users:
                voice_channel_users[channel.id] = []
            if member.id not in voice_channel_users[channel.id]:
                if member.id not in members_dict:
                    members_dict[member.id] = member.name
                voice_channel_users[channel.id].append(member.id)
                print(f"{member.name} joined {channel.name} at {current_time}")
            # updating the VC logs
            
            if member.id not in user_joined_timedate and str(channel.name) == str(checkchannel):
                user_joined_timedate[member.id]= current_time
            if member.id in user_joined_timedate and str(channel.name) == str(checkchannel):
                user_joined_timedate[member.id]= current_time
        
        # Check if the user left a voice channel
        elif before.channel is not None and after.channel is None:
            channel = before.channel
            if channel.id in voice_channel_users:
                if member.id in voice_channel_users[channel.id]:
                    voice_channel_users[channel.id].remove(member.id)
                    print(f"{member.name} left {channel.name} at {current_time}")
                    
            if member.id not in user_left_timedate and str(channel.name) == str(checkchannel):
                user_left_timedate[member.id]= current_time
            if member.id in user_left_timedate and str(channel.name) == str(checkchannel):
                user_left_timedate[member.id]= current_time

        # Check if the user switched voice channels
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            # User left the previous channel
            if before.channel.id in voice_channel_users:
                if member.id in voice_channel_users[before.channel.id]:
                    voice_channel_users[before.channel.id].remove(member.id)
                    print(f"{member.name} left {before.channel.name} at {current_time}")
            channel = before.channel
            if member.id not in user_left_timedate and str(channel.name) == str(checkchannel):
                user_left_timedate[member.id]= current_time
            if member.id in user_left_timedate and str(channel.name) == str(checkchannel):
                user_left_timedate[member.id]= current_time
 
            # User joined the new channel
            
            if after.channel.id not in voice_channel_users:
                voice_channel_users[after.channel.id] = []

            if member.id not in voice_channel_users[after.channel.id]:
                voice_channel_users[after.channel.id].append(member.id)
                print(f"{member.name} joined {after.channel.name} at {current_time}")

            if after.channel.id not in voice_channels:
                    voice_channels[after.channel.id] = after.channel.name
            if member.id not in members_dict:
                members_dict[member.id] = member.name

            channel = after.channel
            if member.id not in user_joined_timedate and str(channel.name) == str(checkchannel):
                user_joined_timedate[member.id]= current_time
            if member.id in user_joined_timedate and str(channel.name) == str(checkchannel):
                user_joined_timedate[member.id]= current_time

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


def is_tracker():
    async def predicate(ctx):
        return curtracker == curauthor
    return commands.check(predicate)
    
# Command to turn the tracking on or off
@bot.command(name="trackoff")
@is_tracker()
async def toggle_trigger(ctx):

    global tracked
    global checkchannel
    global curtracker
    global trackerid
    global trackedlist
    global voice_channel_users

    """Allows users to turn on or off the tracking of the voice channel."""

    print("turning off ... ")
    stop_task()
    sheets.clear_columns(trackerid)
    tracked = False
    checkchannel = None
    curtracker = None
    trackerid = None
    trackedlist = set()
    user_joined_timedate.clear()
    user_left_timedate.clear()
    voice_channels.clear()
    voice_channel_users.clear()
    members_dict.clear()
    member_status.clear()
    
    # Call the clear functions for clearing the lists and timers columns.

    await ctx.send("Voice channel tracking is now OFF.")


# Error handler for the 'toggle_trigger' command
@toggle_trigger.error
async def toggle_trigger_error(ctx, error):
    """Handles missing argument errors for the toggle_trigger command."""
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f'Error: Please specify "off" `%trackoff` to toggle the tracker off and `%trackme @username` to toggle tracker on. Or you are not the current tracker {curtracker}' )
    else:
        await ctx.send(f'Error: Please specify "off" `%trackoff` to toggle the tracker off and `%trackme @username` to toggle tracker on. Or you are not the current tracker {curtracker}' )

async def debounce_process():
    global debounce_timer
    if debounce_timer:
        debounce_timer.cancel()  # Cancel existing timer if there’s a new event
    debounce_timer = asyncio.get_event_loop().call_later(1, lambda: create_task(process_joins_and_leaves()))

@bot.event
async def on_command_error(ctx, error):
    """Handles errors for commands, including unknown commands."""
    
    # Check if the error is CommandNotFound (unknown command)
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"Error: Unknown command. Use `!help` to see available commands.")
    
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