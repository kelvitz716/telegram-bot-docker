import os
import asyncio
import logging
from collections import defaultdict

import telegram
from telegram import Update, Bot
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
    ExtBot
)

import google.generativeai as genai

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Function to get secret from Docker secret file
def get_docker_secret(secret_name):
    try:
        with open(f'/run/secrets/{secret_name}', 'r') as secret_file:
            return secret_file.read().strip()
    except FileNotFoundError:
        return None

# Function to get secret value
def get_secret(secret_name):
    secret_value = os.getenv(secret_name)
    if secret_value is None:
        # Try to get from Docker secret
        secret_value = get_docker_secret(secret_name)
    if secret_value is None:
        raise ValueError(f"No {secret_name} found in environment variables or Docker secrets!")
    return secret_value

# Set up Gemini API
gemini_api_key = get_secret("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)

# Model configuration
generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,
    "response_mime_type": "text/plain",
}
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "threshold": "BLOCK_MEDIUM_AND_ABOVE",
    },
    {
        "category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE",
    },
]

# Model instances
gemini_flash_model = genai.GenerativeModel(
    model_name="gemini-1.5-flash-latest",
    safety_settings=safety_settings,
    generation_config=generation_config,
    system_instruction="Intelligent assistant",
)
gemini_pro_model = genai.GenerativeModel(
    model_name="gemini-1.5-pro",  # Assuming this is for images
    safety_settings=safety_settings,
    generation_config=generation_config,
    system_instruction="Intelligent assistant",
)

# Conversation history (using a single list for each user)
MAX_HISTORY = 50
conversations = defaultdict(lambda: [])
default_model_dict = defaultdict(lambda: gemini_pro_model)

# Predefined messages
GENERATING_RESPONSE = "🤖Generating🤖"
DOWNLOADING_PIC = "🤖Loading picture🤖"
ERROR_INFO = "⚠️⚠️⚠️\nSomething went wrong !\nPlease try to change your prompt or contact the admin !"

# --- Utility Functions ---
async def send_message(player, message):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, player.send_message, message)


async def async_generate_content(model, contents):
    loop = asyncio.get_running_loop()

    def generate():
        return model.generate_content(contents=contents)

    response = await loop.run_in_executor(None, generate)
    return response


# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome, you can ask me questions now. \nFor example: `Who is john lennon?`"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    conversations[user_id].clear()
    await update.message.reply_text("Your history has been cleared")


async def switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if update.message.chat.type != "private":
        await update.message.reply_text("This command is only for private chat!")
        return

    current_model = default_model_dict[user_id]
    if current_model == gemini_pro_model:
        default_model_dict[user_id] = gemini_flash_model
        await update.message.reply_text("Now you are using gemini-1.5-flash")
    else:
        default_model_dict[user_id] = gemini_pro_model
        await update.message.reply_text("Now you are using gemini-1.5-pro")


async def process_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_message = update.message.text

    generating_message = await update.message.reply_text(GENERATING_RESPONSE)

    try:
        # Get conversation history and model
        history = conversations[user_id]
        model = default_model_dict[user_id]

        # Append messages to history
        history.append(
            {"role": "user", "parts": [user_message.strip()]}
        )
        # Limit history
        history = history[-MAX_HISTORY:]

        # Create a new chat session
        chat_session = model.start_chat(history=history)

        response = chat_session.send_message(user_message)
        history.append(
            {"role": "model", "parts": [response.text.strip()]}
        )
        conversations[user_id] = history

        await generating_message.edit_text(response.text)

    except Exception as e:
        logger.error(f"Error processing text message: {e}")
        await update.message.reply_text(ERROR_INFO)


async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = update.message
    bot = context.application.bot

    # Determine the model (public vs private)
    if message.chat.type != "private":
        model = gemini_flash_model
    else:
        model = gemini_pro_model

    try:
        file = message.photo[-1]  # Get the last photo file
        file_id = file.file_id

        sent_message = await update.message.reply_text("Image received")
        
        # Get file object from Telegram using file_id
        file_info = await context.bot.get_file(file_id)
        
        # Download the file as a bytearray
        downloaded_file_bytearray = await file_info.download_as_bytearray()

        # Convert bytearray to bytes
        downloaded_file = bytes(downloaded_file_bytearray)

        # Build the prompt based on caption availability
        prompt_parts = [
            "Image caption:\n",
            message.caption.strip() if message.caption else "",
            "\n",
        ]

        contents = {
            "parts": [
                {"mime_type": "image/jpeg", "data": downloaded_file},
                {"text": ''.join(prompt_parts)},  # Combine caption parts
            ]
        }

        await bot.edit_message_text(
            GENERATING_RESPONSE, chat_id=sent_message.chat.id, message_id=sent_message.message_id
        )
        response = await async_generate_content(model, contents)
        await bot.edit_message_text(
            response.text, chat_id=sent_message.chat.id, message_id=sent_message.message_id
        )

    except Exception as e:
        logger.error(f"Error processing image: {e}")
        await update.message.reply_text(ERROR_INFO)


# --- Main Function ---
def main() -> None:

    token = get_secret("TELEGRAM_BOT_TOKEN")

    """Start the bot."""
    application = (
        Application.builder().token(token).build()
    )
    bot = application.bot

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(CommandHandler("switch", switch))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, process_text)
    )
    application.add_handler(MessageHandler(filters.PHOTO, process_photo))

    # Start the Bot
    application.run_polling()


if __name__ == "__main__":
    main()
