import discord
from discord.ext import commands
from discord import app_commands
import random
import json
import asyncio
from datetime import datetime, timezone, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN_1")

RESULT_CHANNEL_ID = 1450116327489540177
LOG_CHANNEL_ID = 1395052296236306583

COUNTRY_FILE = "country.json"
DATA_FILE = "data.json"

# --- データ処理関数 ---
def load_json(file, default):
    if not os.path.exists(file):
        with open(file, "w", encoding="utf8") as f:
            json.dump(default, f, indent=2, ensure_ascii=False)
        return default
    with open(file, "r", encoding="utf8") as f:
        return json.load(f)

def save_json(file, data):
    with open(file, "w", encoding="utf8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ロード
country_data = load_json(COUNTRY_FILE, {"123456789": "テスト"})
data_store = load_json(DATA_FILE, {"threads": {}, "last_lp": {}})

def get_country(user_id):
    return country_data.get(str(user_id), f"user-{user_id}")

def get_days():
    jst = timezone(timedelta(hours=9))
    start = datetime(2026, 3, 8, tzinfo=jst)
    now = datetime.now(jst)
    return max(1, (now.date() - start.date()).days + 1)

def calc_resource(provs):
    days = get_days()
    total_mp = 0
    total_ap = 0
    for _ in range(provs):
        mp = random.randint(1, 50)
        for _ in range(days):
            v = random.randint(1, 25)
            s = random.randint(1, 3)
            mp += v if s != 1 else -v
        total_mp += mp
        ap = random.randint(1, 50)
        for _ in range(days):
            v = random.randint(1, 25)
            s = random.randint(1, 3)
            ap += v if s != 1 else -v
        total_ap += ap
    return max(0, total_mp), max(0, total_ap)

def generate_pp(mp, ap, use_limit, provs):
    min_required = provs * 50
    target = max(use_limit, min_required)
    possible = min(mp, ap) * 10
    pp = min(possible, target)
    used = pp // 10
    mp -= used
    ap -= used
    return int(pp), int(mp), int(ap)

# --- 敗北時ペナルティ入力 Modal (結果送信機能追加) ---
class DefeatModal(discord.ui.Modal, title="敗北ペナルティ入力"):
    lp_input = discord.ui.TextInput(
        label="次回時ペナルティ正の数で入力してください",
        style=discord.TextStyle.short,
        placeholder="例: 10",
        required=True
    )

    def __init__(self, mp, ap, provs, author):
        super().__init__()
        self.mp = mp
        self.ap = ap
        self.provs = provs
        self.author = author

    async def on_submit(self, interaction: discord.Interaction):
        try:
            lp = int(self.lp_input.value)
        except ValueError:
            await interaction.response.send_message("数字を入力してください。", ephemeral=True)
            return

        thread_id = str(interaction.channel.id)
        # データの保存
        data_store.setdefault("last_lp", {})[thread_id] = lp
        data_store.setdefault("threads", {})[thread_id] = {
            "MP": self.mp,
            "AP": self.ap,
            "PP": 0,
            "LP": lp,
            "provs": int(self.provs),
            "last_date": str(datetime.now(timezone(timedelta(hours=9))).date()),
            "thread_id": thread_id,
        }
        save_json(DATA_FILE, data_store)

        # --- 戦績報告チャンネルへの送信 ---
        country = get_country(self.author.id)
        thread_link = interaction.channel.jump_url
        result_message = f"戦争：{thread_link}\n結果：{country}の敗北"
        
        if RESULT_CHANNEL_ID != 0 and interaction.guild:
            res_ch = interaction.guild.get_channel(RESULT_CHANNEL_ID)
            if res_ch:
                await res_ch.send(result_message)

        await interaction.response.send_message(f"次回時ペナルティを記録し、戦績を報告しました。")


# --- 勝利・敗北 選択 View (結果送信機能追加) ---
# --- 勝利・敗北 選択 View (タイムアウト対策版) ---
class ArmyResultView(discord.ui.View):
    def __init__(self, mp, ap, provs, author):
        super().__init__(timeout=None)
        self.mp = mp
        self.ap = ap
        self.provs = provs
        self.author = author

    @discord.ui.button(label="勝利", style=discord.ButtonStyle.success)
    async def win(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("コマンド実行者のみ操作できます", ephemeral=True)
        
        # 1. 最初に「考え中」状態にする（3秒ルールを回避）
        await interaction.response.defer()

        # ボタン無効化
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

        # --- 戦績報告チャンネルへの送信 ---
        country = get_country(self.author.id)
        thread_link = interaction.channel.jump_url
        result_message = f"戦争：{thread_link}\n結果：{country}の勝利"
        
        if RESULT_CHANNEL_ID != 0 and interaction.guild:
            res_ch = interaction.guild.get_channel(RESULT_CHANNEL_ID)
            if res_ch:
                await res_ch.send(result_message)

        # 2. deferした後は send_message ではなく followup.send を使う
        await interaction.followup.send(
            f"勝利報告を送信しました。資金力：{self.mp}と人的資源：{self.ap}を獲得しました。",
            view=DiceView(self.provs)
        )

    @discord.ui.button(label="敗北", style=discord.ButtonStyle.danger)
    async def lose(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("コマンド実行者のみ操作できます", ephemeral=True)
        
        # 敗北（Modal表示）はDiscordの仕様上、defer()を使わずに即座に応答する必要があるためそのまま
        await interaction.response.send_modal(DefeatModal(self.mp, self.ap, self.provs, self.author))
        
        # ボタン無効化
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

# --- 既存：Views ---
class DiceView(discord.ui.View):
    def __init__(self, provs: int):
        super().__init__(timeout=None)
        self.provs = max(1, int(provs))

    @discord.ui.button(label="デイリーダイス増加量を決定", style=discord.ButtonStyle.success)
    async def roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        await interaction.message.edit(view=self)

        total = 0
        for _ in range(self.provs):
            n = random.randint(1, 5) - 2
            if n <= 1: inc = 1
            elif n == 2: inc = 2
            else: inc = 3
            total += inc
        await interaction.response.send_message(f"デイリーダイス {total} 増加しました。")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- 他のView（ExecuteViewなど）は変更なしのため省略可能ですが構造維持のために配置 ---
class ExecuteView(discord.ui.View):
    def __init__(self, provs, use_limit, pp, mp, ap, author, lp=0):
        super().__init__(timeout=None)
        self.provs = provs
        self.use_limit = use_limit
        self.pp = pp
        self.mp = mp
        self.ap = ap
        self.author = author
        self.lp = lp

    @discord.ui.button(label="処理を実行", style=discord.ButtonStyle.primary)
    async def execute(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("コマンド実行者のみ操作できます", ephemeral=True)
            return
        button.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(
            "自身の軍事力の出目を決定",
            view=PlayerRollView(self.use_limit, self.pp, self.mp, self.ap, self.provs, self.author, lp=0),
        )

class PlayerRollView(discord.ui.View):
    def __init__(self, player_limit, pp, mp, ap, provs, author, lp=0):
        super().__init__(timeout=None)
        self.player_limit = max(1, int(player_limit))
        self.pp = pp
        self.mp = mp
        self.ap = ap
        self.provs = provs
        self.author = author
        self.lp = lp
        self.current = random.randint(1, self.player_limit)
        self.task = asyncio.create_task(self._rolling())

    async def _rolling(self):
        try:
            while True:
                self.current = random.randint(1, self.player_limit)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            return

    @discord.ui.button(label="自身の軍事力の出目を決定する", style=discord.ButtonStyle.primary)
    async def decide(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("コマンド実行者のみ操作できます", ephemeral=True)
            return
        self.task.cancel()
        button.disabled = True
        await interaction.message.edit(view=self)
        plap = int(self.current)
        if self.lp > 0:
            plap = max(0, plap - self.lp)
            msg = f"あなたの出目：{self.current}\nLPデバフ -{self.lp} → 最終PLAP：{plap}"
        else:
            msg = f"あなたの出目：{plap}"
        await interaction.response.send_message(
            msg,
            view=NPCRollView(plap, self.pp, self.mp, self.ap, self.provs, self.author, self.lp)
        )

class NPCRollView(discord.ui.View):
    def __init__(self, plap, npc_limit, mp, ap, provs, author, lp=0):
        super().__init__(timeout=None)
        self.plap = int(plap)
        self.lp = int(lp)
        self.npc_limit = max(1, int(npc_limit))
        self.mp = int(mp)
        self.ap = int(ap)
        self.provs = provs
        self.author = author
        self.current = random.randint(1, self.npc_limit)
        self.task = asyncio.create_task(self._rolling())

    async def _rolling(self):
        try:
            while True:
                self.current = random.randint(1, self.npc_limit)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            return

    @discord.ui.button(label="相手の軍事力の出目を決定する", style=discord.ButtonStyle.danger)
    async def decide(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("コマンド実行者のみ操作できます", ephemeral=True)
            return
        self.task.cancel()
        button.disabled = True
        await interaction.message.edit(view=self)
        npcap = int(self.current)
        await interaction.response.send_message(f"NPCの出目：{npcap}")

        channel = interaction.channel
        thread_id = str(channel.id)
        thread_link = channel.jump_url

        if self.plap > npcap:
            await interaction.followup.send("勝利！")
            await interaction.followup.send(f"獲得する資金力：{self.mp}、獲得する人的資源：{self.ap}")
            await interaction.followup.send("デイリーダイス増加量を決定", view=DiceView(int(self.provs)))
        else:
            lp = npcap - self.plap
            await interaction.followup.send(f"次回戦争時に-{lp}のデバフがPL側にかかります")
            data_store.setdefault("last_lp", {})[thread_id] = lp
            data_store.setdefault("threads", {})[thread_id] = {
                "MP": self.mp, "AP": self.ap, "PP": 0, "LP": lp,
                "provs": int(self.provs),
                "last_date": str(datetime.now(timezone(timedelta(hours=9))).date()),
                "thread_id": thread_id,
            }
            save_json(DATA_FILE, data_store)

        country = get_country(self.author.id)
        result_text = f"{country}の勝利" if self.plap > npcap else f"{country}の敗北"
        result_message = f"戦争：{thread_link}\n結果：{result_text}"
        if RESULT_CHANNEL_ID != 0 and interaction.guild:
            res_ch = interaction.guild.get_channel(RESULT_CHANNEL_ID)
            if res_ch: await res_ch.send(result_message)
        if LOG_CHANNEL_ID != 0 and interaction.guild:
            log_ch = interaction.guild.get_channel(LOG_CHANNEL_ID)
            if log_ch:
                await log_ch.send(f"戦争スレッド：{thread_link}\n\n戦争後\nMP：{self.mp}\nAP：{self.ap}\nPP：0")

# --- Commands ---
@bot.tree.command(name="npc_army", description="NPC軍事力算出")
async def npc_army(interaction: discord.Interaction, provs: int, use_limit: int):
    provs = max(1, int(provs))
    use_limit = max(1, int(use_limit))

    mp = ap = pp = mp_remain = ap_remain = 0
    for _ in range(20):
        mp, ap = calc_resource(provs)
        pp, mp_remain, ap_remain = generate_pp(mp, ap, use_limit, provs)
        if pp > 0: break
    else:
        await interaction.response.send_message("資源算出に失敗しました。もう一度お試しください。")
        return

    thread_link = interaction.channel.jump_url
    if LOG_CHANNEL_ID != 0 and interaction.guild:
        log_ch = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            await log_ch.send(f"軍事力算出：{thread_link}\n\nMP：{mp_remain}\nAP：{ap_remain}\nPP：{pp}")

    # 勝利・敗北ボタン付きでメッセージを送信
    view = ArmyResultView(mp_remain, ap_remain, provs, interaction.user)
    await interaction.response.send_message(
        f"使用軍事力：||{pp}||",
        view=view
    )

@bot.tree.command(name="npc_war")
async def npc_war(interaction: discord.Interaction, provs: int, use_limit: int):
    # (既存のnpc_war処理 そのまま)
    provs = max(1, int(provs))
    use_limit = max(1, int(use_limit))
    mp = ap = pp = mp_remain = ap_remain = 0
    for _ in range(20):
        mp, ap = calc_resource(provs)
        pp, mp_remain, ap_remain = generate_pp(mp, ap, use_limit, provs)
        if pp > 0: break
    else:
        await interaction.response.send_message("資源算出に失敗しました。")
        return
    thread_link = interaction.channel.jump_url
    if LOG_CHANNEL_ID != 0 and interaction.guild:
        log_ch = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_ch: await log_ch.send(f"戦争スレッド：{thread_link}\n\n戦争前\nMP：{mp_remain}\nAP：{ap_remain}\nPP：{pp}")
    await interaction.response.send_message(
        f"使用軍事力：||{pp}||",
        view=ExecuteView(provs, use_limit, pp, mp_remain, ap_remain, interaction.user, lp=0),
    )

@bot.tree.command(name="npc_rematch")
async def npc_rematch(interaction: discord.Interaction, use_limit: int):
    # (既存のnpc_rematch処理 そのまま)
    thread_id = str(interaction.channel.id)
    if thread_id not in data_store.get("threads", {}):
        await interaction.response.send_message("再戦データがありません")
        return
    saved = data_store["threads"][thread_id]
    mp, ap, lp, provs = int(saved.get("MP", 0)), int(saved.get("AP", 0)), int(saved.get("LP", 0)), int(saved.get("provs", 1))
    last_date = datetime.fromisoformat(saved["last_date"]).date()
    days = max(1, (datetime.now().date() - last_date).days)
    for _ in range(provs):
        for _ in range(days):
            v = random.randint(1, 25); s = random.randint(1, 3)
            mp += v if s != 1 else -v
            v = random.randint(1, 25); s = random.randint(1, 3)
            ap += v if s != 1 else -v
    mp, ap = max(0, mp), max(0, ap)
    for _ in range(20):
        pp, mp_remain, ap_remain = generate_pp(mp, ap, use_limit, provs)
        if pp > 0: break
        mp, ap = calc_resource(provs)
    else:
        await interaction.response.send_message("資源算出に失敗しました。")
        return
    thread_link = interaction.channel.jump_url
    if LOG_CHANNEL_ID != 0 and interaction.guild:
        log_ch = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_ch: await log_ch.send(f"戦争スレッド：{thread_link}\n\n戦争前\nMP：{mp_remain}\nAP：{ap_remain}\nPP：{pp}\nLPデバフ：{lp}")
    await interaction.response.send_message(
        f"使用軍事力：||{pp}||",
        view=ExecuteView(provs, use_limit, pp, mp_remain, ap_remain, interaction.user),
    )

@bot.tree.command(name="npc_army_rematch", description="再戦用のNPC軍事力算出（手動結果入力版）")
async def npc_army_rematch(interaction: discord.Interaction, use_limit: int):
    use_limit = max(1, int(use_limit))
    
    # ---- 1. 再戦データの取得（/npc_rematch と同じ） ----
    thread_id = str(interaction.channel.id)
    if thread_id not in data_store.get("threads", {}):
        await interaction.response.send_message("再戦データがありません。このチャンネルで過去に敗北した記録が必要です。", ephemeral=True)
        return

    saved = data_store["threads"][thread_id]
    mp = int(saved.get("MP", 0))
    ap = int(saved.get("AP", 0))
    lp = int(saved.get("LP", 0))
    provs = int(saved.get("provs", 1))

    # ---- 2. 前回戦闘日から現在までの経過日数で資源を追加（/npc_rematch と同じ） ----
    last_date_str = saved.get("last_date")
    last_date = datetime.fromisoformat(last_date_str).date()
    today = datetime.now(timezone(timedelta(hours=9))).date()
    days = (today - last_date).days
    
    # 1日未満でも最低1日は経過したとして計算
    if days < 1:
        days = 1

    # 資源の成長計算
    for _ in range(provs):
        for _ in range(days):
            v = random.randint(1, 25)
            s = random.randint(1, 3)
            mp += v if s != 1 else -v
            
            v = random.randint(1, 25)
            s = random.randint(1, 3)
            ap += v if s != 1 else -v

    mp = max(0, mp)
    ap = max(0, ap)

    # ---- 3. PP算出ループ ----
    pp = mp_remain = ap_remain = 0
    for _ in range(20):
        pp, mp_remain, ap_remain = generate_pp(mp, ap, use_limit, provs)
        if pp > 0:
            break
        # 失敗時は完全再算出
        mp, ap = calc_resource(provs)
    else:
        await interaction.response.send_message("資源算出に失敗しました。もう一度お試しください。")
        return

    # ---- 4. ログ送信（LP情報を含める） ----
    thread_link = interaction.channel.jump_url
    if LOG_CHANNEL_ID != 0 and interaction.guild:
        log_ch = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_ch:
            await log_ch.send(
                f"再戦軍事力算出：{thread_link}\n\n"
                f"MP：{mp_remain}\n"
                f"AP：{ap_remain}\n"
                f"PP：{pp}\n"
                f"適用されていたLPデバフ：{lp}"
            )

    # ---- 5. 勝利・敗北ボタン付きで送信 ----
    # 前回のLPはすでに反映済みとして、ArmyResultViewには新しい資源状態を渡す
    view = ArmyResultView(mp_remain, ap_remain, provs, interaction.user)
    
    await interaction.response.send_message(
        f"【再戦】使用軍事力：||{pp}||\n(前回からのデバフ {lp} を考慮してPL側は計算してください)",
        view=view
    )

@bot.tree.command(name="pl_country", description="プレイヤー国登録")
async def pl_country(interaction: discord.Interaction, user_id: str, country_name: str):
    country_data[user_id] = country_name
    save_json(COUNTRY_FILE, country_data)
    await interaction.response.send_message(f"登録しました\nユーザーID：{user_id}\n国名：{country_name}")

@bot.event
async def on_ready():
    print("BOT起動")
    await bot.tree.sync()

if __name__ == "__main__":
    bot.run(TOKEN)
