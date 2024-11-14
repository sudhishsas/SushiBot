import random


def handle_response(message):
    
    if message.content[0] == '!':
        
        p_message = message.content[1:].lower()

    if p_message == 'hello':
        return 'Hey there!'
    
    if p_message == 'roll':
        return str(random.randint(1, 6))
    
    if p_message == 'help':
        return "`This is a help message that you can modify.`"
