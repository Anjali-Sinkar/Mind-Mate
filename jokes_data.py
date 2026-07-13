import random

JOKES = {

    "programming": [

        "Debugging is like being a detective in a movie where you're also the criminal. 😄",

        "My code works. I have no idea why. My code doesn't work. I also have no idea why.",

        "Programmers don't make mistakes. We create unexpected features.",

        "I asked my code to behave today. It threw another exception.",

        "My keyboard knows all my secrets... especially Ctrl+C and Ctrl+V.",

        "404: Motivation not found. Reloading with coffee... ☕",

        "Python never judges me. It just tells me exactly where I messed up.",

        "There's no place like 127.0.0.1.",

        "Sometimes I talk to my code. It usually responds with an error message."

    ],

    "student": [

        "My brain has 42 tabs open. Somewhere, music is playing and I can't find it. 😂",

        "Exams are basically speed dating with your memory.",

        "I opened my textbook... progress was made.",

        "Tomorrow's exam and today's motivation are not on speaking terms.",

        "Group projects teach patience more than teamwork.",

        "Studying is like updating an app. It always takes longer than expected.",

        "My notes are beautifully organized. My brain isn't.",

        "Coffee and deadlines have a suspiciously strong friendship."

    ],

    "office": [

        "Meetings could have been emails... and emails could have been one sentence.",

        "My to-do list keeps adding side quests.",

        "Monday feels personally invested in testing everyone's patience.",

        "My laptop and I both need coffee before functioning properly.",

        "Every time I clear my inbox, it somehow grows back.",

        "I'm not procrastinating... I'm strategically delaying."

    ],

    "everyday": [

        "I finally cleaned my room. Now I can't find anything.",

        "My plant is thriving. Clearly one of us knows what they're doing. 🌱",

        "I told my pillow we'd sleep early tonight. It looked unconvinced.",

        "Sometimes adulthood feels like clicking 'Remind me tomorrow' on life.",

        "Laundry multiplies when nobody is looking."

    ],

    "animals": [

        "If dogs ran the world, meetings would last 30 seconds and include treats.",

        "Cats look like they know the meaning of life but refuse to tell us.",

        "A penguin walking confidently can improve almost anyone's mood."

    ],

    "food": [

        "Pizza never asks difficult questions. It just shows up when needed. 🍕",

        "Chocolate has excellent listening skills.",

        "If calories came from laughing, we'd all be nutrition experts."

    ],

    "wholesome": [

        "Tiny progress still counts as progress.",

        "You don't have to have everything figured out today.",

        "Your worth isn't measured by how productive today was.",

        "It's okay if today wasn't perfect. Tomorrow is another page, not another judgment.",

        "Taking a break isn't giving up. It's making sure you can keep going."

    ]
}

def get_all_jokes():
    """Return every joke from every category as a single flat list."""
    all_jokes = []
    for jokes in JOKES.values():
        all_jokes.extend(jokes)
    return all_jokes


def get_random_joke(category=None):
    """
    Returns a random joke.
    If category doesn't exist, choose from every category.
    """

    if category and category in JOKES:
        return random.choice(JOKES[category])

    all_jokes = get_all_jokes()
    if not all_jokes:
        return "A little humor is on the way."
    return random.choice(all_jokes)