import re
import shlex
import asyncio
import base64
from io import BytesIO
from dataclasses import dataclass
from asyncio import TimerHandle
from tracemalloc import stop
from typing import Dict, List, Optional, NoReturn

from sqlalchemy import true

import hoshino
from hoshino import Service
from hoshino.typing import CQEvent

from nonebot import MessageSegment

from .utils import dic_list, random_word
from .data_source import Wordle, GuessResult
HELP_MSG1 = '''
		输入 猜单词开始游戏；\n
		eg:猜单词 5 CET4
		eg:我猜 monday
		第二个参数为单词长度 默认为5
		第三个参数为词库 默认为四级
		
		答案为指定长度单词，发送对应长度单词即可；\n
		绿色块代表此单词中有此字母且位置正确；\n
		黄色块代表此单词中有此字母，但该字母所处位置不对；\n
		灰色块代表此单词中没有此字母；\n
		猜出单词或用光次数则游戏结束；\n
		发送“结束”结束游戏；发送“提示”查看提示；\n
		
		
'''
HELP_MSG2 = f"支持的词典：{'、'.join(dic_list)}"
HELP_MSG = HELP_MSG1+HELP_MSG2
sv = hoshino.Service('猜单词',visible = True,enable_on_default=True, help_=HELP_MSG)

# parser = ArgumentParser("wordle", description="猜单词")
# parser.add_argument("-l", "--length", type=int, default=5, help="单词长度")
# parser.add_argument("-d", "--dic", default="CET4", help="词典")
# parser.add_argument("--hint", action="store_true", help="提示")
# parser.add_argument("--stop", action="store_true", help="结束游戏")
# parser.add_argument("word", nargs="?", help="单词")


@dataclass
class Options:
	length: int = 0
	dic: str = ""
	hint: bool = False
	stop: bool = False
	word: str = ""


games: Dict[str, Wordle] = {}
timers: Dict[str, TimerHandle] = {}


def get_cid(event):
	return (
		f"group_{event.group_id}"
		if event.group_id
		else f"private_{event.user_id}"
	)


def game_running(event) -> bool:
	cid = get_cid(event)
	return bool(games.get(cid, None))


def is_word(msg) -> bool:
	if re.fullmatch(r"^[a-zA-Z]{3,8}$", msg):
		return True
	return False


@sv.on_prefix('猜单词')
async def _(bot, ev: CQEvent):
	cid = get_cid(ev)
	if games.get(cid, None):
		await bot.send(ev,"已有游戏进行中",at_sender = True)
	else:
		args = ev.message.extract_plain_text().split()
		args = [i.upper() for i in args]
		msg = ''
		argv = []
		if len(args) == 0:
			print('0参数')
			await handle_wordle(bot,ev,["--length", "5", "--dic", "CET4"])
		elif len(args) == 1:
			print('1参数')
			if args[0].isdigit():
				argv.append('--length')
				argv.append(args[0])
				argv.append('--dic')
				argv.append('CET4')
			elif args[0] in dic_list:
				argv.append('--dic')
				argv.append(args[0])
				argv.append('--length')
				argv.append('5')
			else:
				await bot.finish(ev,"无效的参数哦",at_sender = True)
			await handle_wordle(bot,ev,argv)	
		elif len(args) == 2:
			print('2参数')
			if args[0].isdigit():
				argv.append('--length')
				argv.append(args[0])
			else:
				await bot.finish(ev,"第一个参数需要是3~8的数字(闭区间)",at_sender = True)
			if args[1] in dic_list:
				argv.append('--dic')
				argv.append(args[1])
			else:
				await bot.finish(ev,"第二个参数需要是支持的字典",at_sender = True)
			await handle_wordle(bot,ev,argv)
		else:
			print('不行参数')
			await bot.finish(ev,"无效的猜单词指令哦",at_sender = True)
		

@sv.on_prefix('提示')
async def _(bot,ev):
	await handle_wordle(bot, ev,["--hint"])


@sv.on_prefix('结束猜词',"停", "结束游戏","结束")
async def _(bot,ev):
	await handle_wordle(bot, ev,["--stop"])



@sv.on_prefix("我猜")
async def _(bot, ev):
	uid = ev.user_id
	text = str(ev.message).strip()
	if not text:
		await bot.finish(ev, "单词呢？单词呢？单词捏？", at_sender=True)
	elif not is_word(text):
		await bot.finish(ev, "字母都不会的打咯(3<=长度<=8且均为字母才合法)", at_sender=True)
	else:
		word = text
		await handle_wordle(bot, ev, [word])


async def stop_game(bot,ev, cid: str):
	timers.pop(cid, None)
	if games.get(cid, None):
		game = games.pop(cid)
		msg = "猜单词超时，游戏结束"
		if len(game.guessed_words) >= 1:
			msg += f"\n{game.result}"
		await bot.finish(ev,msg)


def set_timeout(bot, ev,cid: str,timeout: float = 300):
	timer = timers.get(cid, None)
	if timer:
		timer.cancel()
	loop = asyncio.get_running_loop()
	timer = loop.call_later(
		timeout, lambda: asyncio.ensure_future(stop_game(bot,ev,cid))
	)
	timers[cid] = timer


async def handle_wordle(bot, ev,argv: List[str]):
	print("读取",argv)
	async def send(
		message: Optional[str] = None, image: Optional[BytesIO] = None
	) -> NoReturn:
		if not (message or image):
			await bot.finish(ev,'')
		msg = ''
		if image:
			byte_data = image.getvalue()
			base64_str = base64.b64encode(byte_data).decode()
			image = 'base64://' + base64_str
			msg += MessageSegment.image(image)
		if message:
			msg = msg + '\n' + message
		await bot.finish(ev,msg)

	
	args = {'length':0,'dic':"",'hint': False,'stop': False,'word':""}
	N = len(argv)
	if N == 1:
		if(argv[0] == '--hint'):
			args['hint'] = True
		elif argv[0] == '--stop':
			args['stop'] = True
		args["word"] = argv[0]
	else:
		for i in range(0,N):
			if(argv[i] == '--hint'):
				args["hint"] = True
			if(argv[i] == '--stop'):
				args["stop"] = True
			if(argv[i] == '--length'):
				args["length"] = int(argv[i+1])
			if(argv[i] == '--dic'):
				args["dic"] = argv[i+1]
	print("解析",args)
	options = Options(**args)

	cid = get_cid(ev)
	if not games.get(cid, None):
		if options.word or options.stop or options.hint:
			await send("没有正在进行的游戏")

		if not (options.length and options.dic):
			await send("请指定单词长度和词典")

		if options.length < 3 or options.length > 8:
			await send("单词长度应在3~8之间")

		if options.dic not in dic_list:
			await send("支持的词典：" + ", ".join(dic_list))

		word, meaning = random_word(options.dic, options.length)
		print(type(word),word)
		game = Wordle(word, meaning)
		games[cid] = game
		set_timeout(bot,ev,cid)

		await send(f"你有{game.rows}次机会猜出单词，单词长度为{game.length}，请发送单词", game.draw())
	if options.stop:
		game = games.pop(cid)
		msg = "游戏已结束"
		if len(game.guessed_words) >= 1:
			msg += f"\n{game.result}"
		await send(msg)

	game = games[cid]
	set_timeout(bot,ev,cid)

	if options.hint:
		hint = game.get_hint()
		if not hint.replace("*", ""):
			await send("你还没有猜对过一个字母哦~再猜猜吧~")
		await send(image=game.draw_hint(hint))

	word = options.word

	if not re.fullmatch(r"^[a-zA-Z]{3,8}$", word):
		await send()
	if len(word) != game.length:
		await send("请发送正确长度的单词")

	result = game.guess(word)
	if result in [GuessResult.WIN, GuessResult.LOSS]:
		games.pop(cid)
		await send(
			("恭喜你猜出了单词！" if result == GuessResult.WIN else "很遗憾，没有人猜出来呢")
			+ f"\n{game.result}",
			game.draw(),
		)
	elif result == GuessResult.DUPLICATE:
		await send("你已经猜过这个单词了呢")
	elif result == GuessResult.ILLEGAL:
		await send(f"你确定 {word} 是一个合法的单词吗？")
	else:
		await send(image=game.draw())
