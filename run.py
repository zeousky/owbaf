"""Discord transport for the Brainfuck reply engine."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from pathlib import Path

import discord
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
PROGRAMS = ROOT / "brainfuck"
load_dotenv(ROOT / ".env")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("owaua-brainfuck")

PERSONAS = {"rudeish", "nerdish", "flirty", "chaotic"}
user_personas: dict[int, str] = {}
user_languages: dict[int, str] = {}
LANGUAGE_ALIASES = {
    "english": "english",
    "en": "english",
    "spanish": "spanish",
    "es": "spanish",
    "french": "french",
    "fr": "french",
    "german": "german",
    "de": "german",
    "italian": "italian",
    "it": "italian",
    "hungarian": "hungarian",
    "hu": "hungarian",
    "romanian": "romanian",
    "ro": "romanian",
    "polish": "polish",
    "pl": "polish",
    "ukrainian": "ukrainian",
    "uk": "ukrainian",
    "greek": "greek",
    "el": "greek",
}


def load_language_vocabulary(language: str) -> tuple[str, ...]:
    path = PROGRAMS / "languages" / f"{language}.txt"
    words = {
        word.strip()
        for word in path.read_text(encoding="utf-8").split()
        if word.strip()
    }
    if len(words) < 10:
        raise RuntimeError(f"language vocabulary is missing or too small: {language}")
    return tuple(sorted(words))


def load_vocabulary() -> tuple[str, ...]:
    """Load a local English dictionary, with a bundled fallback."""
    candidates = (
        Path("/usr/share/dict/words"),
        Path("/Library/Developer/CommandLineTools/usr/share/dict/words"),
        PROGRAMS / "vocabulary.txt",
    )
    for path in candidates:
        try:
            words = {
                word.strip().casefold()
                for word in path.read_text(encoding="utf-8").split()
                if word.strip().isalpha()
            }
        except (OSError, UnicodeError):
            continue
        if len(words) >= 100:
            return tuple(sorted(words))
    raise RuntimeError("the bundled English vocabulary is missing or too small")


VOCABULARY = load_vocabulary()
LANGUAGE_VOCABULARIES = {
    language: load_language_vocabulary(language)
    for language in set(LANGUAGE_ALIASES.values())
}


def random_sentence(language: str = "english") -> str:
    """Make a deliberately unpredictable sentence from a local language pack."""
    length = secrets.randbelow(9) + 4
    vocabulary = LANGUAGE_VOCABULARIES.get(language, VOCABULARY)
    words = [secrets.choice(vocabulary) for _ in range(length)]
    sentence = " ".join(words)
    return sentence[:1].upper() + sentence[1:] + secrets.choice((".", "!", "?"))


class BrainfuckError(RuntimeError):
    pass


def _jump_table(program: str) -> dict[int, int]:
    stack: list[int] = []
    jumps: dict[int, int] = {}
    for index, instruction in enumerate(program):
        if instruction == "[":
            stack.append(index)
        elif instruction == "]":
            if not stack:
                raise BrainfuckError("unmatched ]")
            opening = stack.pop()
            jumps[opening] = index
            jumps[index] = opening
    if stack:
        raise BrainfuckError("unmatched [")
    return jumps


def run_brainfuck(program_path: Path, input_bytes: bytes = b"") -> str:
    """Execute a Brainfuck source file and return its UTF-8 output."""
    source = program_path.read_text(encoding="utf-8")
    code = "".join(character for character in source if character in "><+-.,[]")
    jumps = _jump_table(code)
    cells = [0] * 30_000
    pointer = 0
    input_index = 0
    output = bytearray()
    instruction = 0
    steps = 0

    while instruction < len(code):
        steps += 1
        if steps > 2_000_000:
            raise BrainfuckError(f"{program_path.name} exceeded the step limit")
        operation = code[instruction]
        if operation == ">":
            pointer += 1
            if pointer >= len(cells):
                raise BrainfuckError("data pointer moved right out of bounds")
        elif operation == "<":
            pointer -= 1
            if pointer < 0:
                raise BrainfuckError("data pointer moved left out of bounds")
        elif operation == "+":
            cells[pointer] = (cells[pointer] + 1) % 256
        elif operation == "-":
            cells[pointer] = (cells[pointer] - 1) % 256
        elif operation == ".":
            output.append(cells[pointer])
        elif operation == ",":
            if input_index < len(input_bytes):
                cells[pointer] = input_bytes[input_index]
                input_index += 1
            else:
                cells[pointer] = 0
        elif operation == "[" and cells[pointer] == 0:
            instruction = jumps[instruction]
        elif operation == "]" and cells[pointer] != 0:
            instruction = jumps[instruction]
        instruction += 1

    return output.decode("utf-8")


def reply(program: str) -> str:
    return run_brainfuck(PROGRAMS / f"{program}.bf")


def selected_persona(user_id: int) -> str:
    return user_personas.get(user_id, "rudeish")


class OwauaBrainfuck(discord.Client):
    async def on_ready(self) -> None:
        log.info("logged in as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        content = message.content.strip()
        mentioned = self.user is not None and self.user in message.mentions
        if self.user is not None:
            content = content.replace(f"<@{self.user.id}>", "").replace(
                f"<@!{self.user.id}>", ""
            ).strip()
        command = content.casefold()

        if command == "!help":
            await message.channel.send(reply("help"))
            return
        if command == "!brainfuck":
            await message.channel.send(reply("brainfuck"))
            return
        if command == "!ping":
            await message.channel.send(reply("ping"))
            return
        if command.startswith("!persona"):
            requested = command.removeprefix("!persona").strip()
            if not requested:
                await message.channel.send(
                    f"persona: {selected_persona(message.author.id)}"
                )
                return
            if requested not in PERSONAS:
                await message.channel.send(
                    "choose rudeish, nerdish, flirty, or chaotic"
                )
                return
            user_personas[message.author.id] = requested
            await message.channel.send(f"persona set to {requested}")
            return
        if command.startswith("!language"):
            requested = command.removeprefix("!language").strip()
            if not requested:
                await message.channel.send(
                    f"language: {user_languages.get(message.author.id, 'english')}"
                )
                return
            if requested == "random":
                language = secrets.choice(tuple(LANGUAGE_VOCABULARIES))
            else:
                language = LANGUAGE_ALIASES.get(requested)
            if language is None:
                choices = ", ".join(sorted(set(LANGUAGE_ALIASES.values())))
                await message.channel.send(f"choose one of: {choices}, random")
                return
            user_languages[message.author.id] = language
            await message.channel.send(f"language set to {language}")
            return

        if mentioned:
            language = user_languages.get(message.author.id, "english")
            generated = random_sentence(language)
            # The Python adapter supplies randomness; the Brainfuck program
            # still performs the actual output by echoing these bytes.
            await message.channel.send(
                run_brainfuck(PROGRAMS / "random.bf", generated.encode("utf-8"))
            )


async def main() -> None:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing; copy .env.example to .env")
    intents = discord.Intents.default()
    intents.message_content = True
    try:
        await OwauaBrainfuck(intents=intents).start(token)
    except discord.PrivilegedIntentsRequired as exc:
        raise RuntimeError(
            "Discord rejected Message Content Intent. Enable it at "
            "Developer Portal -> your application -> Bot -> Privileged Gateway "
            "Intents -> Message Content Intent, then restart the bot."
        ) from exc


if __name__ == "__main__":
    asyncio.run(main())
