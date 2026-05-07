"""
🎰 Discord 抽獎機器人
功能：
  - /抽獎面板  → 發送一個嵌入式控制面板（含按鈕）
  - /建立抽獎  → 透過表單建立抽獎活動
  - /指定抽獎  → 指定成員並抽出中獎者
  
需要安裝：pip install discord.py
"""

import discord
from discord import app_commands, ui
from discord.ext import commands
import random
import asyncio
from datetime import datetime
from typing import Optional

# ============================================================
#  設定區：請填入你的 Bot Token
# ============================================================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# ============================================================
#  Bot 初始化
# ============================================================
intents = discord.Intents.default()
intents.members = True          # 需要開啟「Server Members Intent」
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 儲存進行中的抽獎活動 { guild_id: { 抽獎名稱: {...} } }
active_lotteries = {}


# ============================================================
#  事件：Bot 上線
# ============================================================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ 機器人已上線：{bot.user}")
    print(f"📡 已加入 {len(bot.guilds)} 個伺服器")


# ============================================================
#  建立抽獎的 Modal 表單
# ============================================================
class LotteryModal(ui.Modal, title="🎰 建立抽獎活動"):
    lottery_name = ui.TextInput(
        label="抽獎名稱",
        placeholder="例如：每週幸運抽獎",
        required=True,
        max_length=50,
    )
    prize = ui.TextInput(
        label="獎品說明",
        placeholder="例如：Steam 遊戲序號 x1",
        required=True,
        max_length=200,
    )
    winner_count = ui.TextInput(
        label="中獎人數",
        placeholder="例如：3",
        required=True,
        max_length=3,
    )
    description = ui.TextInput(
        label="活動說明（選填）",
        style=discord.TextStyle.paragraph,
        placeholder="填寫抽獎的額外說明...",
        required=False,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # 驗證中獎人數
        try:
            count = int(self.winner_count.value)
            if count < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ 中獎人數必須是正整數！", ephemeral=True)
            return

        guild_id = interaction.guild_id
        if guild_id not in active_lotteries:
            active_lotteries[guild_id] = {}

        lottery_key = self.lottery_name.value
        active_lotteries[guild_id][lottery_key] = {
            "name": self.lottery_name.value,
            "prize": self.prize.value,
            "winner_count": count,
            "description": self.description.value or "無",
            "participants": [],       # 指定的參加者
            "creator": interaction.user.id,
            "created_at": datetime.now(),
        }

        # 發送確認訊息 + 成員選擇面板
        embed = discord.Embed(
            title=f"🎰 抽獎活動已建立：{self.lottery_name.value}",
            color=0xFFD700,
        )
        embed.add_field(name="🎁 獎品", value=self.prize.value, inline=True)
        embed.add_field(name="👥 中獎人數", value=f"{count} 人", inline=True)
        embed.add_field(name="📝 說明", value=self.description.value or "無", inline=False)
        embed.add_field(name="📋 已指定成員", value="尚未指定任何成員", inline=False)
        embed.set_footer(text=f"建立者：{interaction.user.display_name}")

        view = LotteryManageView(lottery_key, guild_id)
        await interaction.response.send_message(embed=embed, view=view)


# ============================================================
#  成員選擇下拉選單（一次可選多人）
# ============================================================
class MemberSelect(ui.UserSelect):
    def __init__(self, lottery_key: str, guild_id: int):
        super().__init__(
            placeholder="選擇要加入抽獎的成員...",
            min_values=1,
            max_values=25,  # 最多一次選 25 人
        )
        self.lottery_key = lottery_key
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message("❌ 找不到此抽獎活動！", ephemeral=True)
            return

        # 將選取的成員加入參加者名單（去重）
        existing_ids = {m.id for m in lottery["participants"]}
        added = []
        for member in self.values:
            if member.id not in existing_ids and not member.bot:
                lottery["participants"].append(member)
                added.append(member.display_name)

        if added:
            member_list = "\n".join(
                f"　`{i+1}.` {m.display_name}"
                for i, m in enumerate(lottery["participants"])
            )
            # 更新原訊息的 embed
            embed = interaction.message.embeds[0]
            # 更新「已指定成員」欄位
            for i, field in enumerate(embed.fields):
                if field.name == "📋 已指定成員":
                    embed.set_field_at(
                        i,
                        name=f"📋 已指定成員（共 {len(lottery['participants'])} 人）",
                        value=member_list[:1024],  # Discord 欄位上限
                        inline=False,
                    )
                    break

            await interaction.response.edit_message(embed=embed)
        else:
            await interaction.response.send_message(
                "⚠️ 所選的成員已經在名單中，或是機器人不可參加。", ephemeral=True
            )


# ============================================================
#  抽獎管理面板（按鈕 + 選單）
# ============================================================
class LotteryManageView(ui.View):
    def __init__(self, lottery_key: str, guild_id: int):
        super().__init__(timeout=None)
        self.lottery_key = lottery_key
        self.guild_id = guild_id

        # 加入成員選擇下拉選單
        self.add_item(MemberSelect(lottery_key, guild_id))

    @ui.button(label="🎲 開始抽獎", style=discord.ButtonStyle.success, row=2)
    async def draw_button(self, interaction: discord.Interaction, button: ui.Button):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message("❌ 找不到此抽獎活動！", ephemeral=True)
            return

        # 檢查權限（只有建立者可以開獎）
        if interaction.user.id != lottery["creator"]:
            await interaction.response.send_message("❌ 只有抽獎建立者可以開獎！", ephemeral=True)
            return

        participants = lottery["participants"]
        winner_count = lottery["winner_count"]

        if len(participants) == 0:
            await interaction.response.send_message("❌ 尚未指定任何參加成員！", ephemeral=True)
            return

        if len(participants) < winner_count:
            await interaction.response.send_message(
                f"❌ 參加人數（{len(participants)}）少於中獎人數（{winner_count}），請增加成員！",
                ephemeral=True,
            )
            return

        # ── 開獎動畫 ──
        await interaction.response.defer()

        # 倒數動畫
        countdown_embed = discord.Embed(title="🎰 抽獎即將開始...", color=0xFF6B6B)
        msg = await interaction.followup.send(embed=countdown_embed)

        for i in [3, 2, 1]:
            countdown_embed.description = f"# {i}"
            await msg.edit(embed=countdown_embed)
            await asyncio.sleep(1)

        # 抽出中獎者
        winners = random.sample(participants, winner_count)

        # 結果 Embed
        result_embed = discord.Embed(
            title=f"🎉 抽獎結果：{lottery['name']}",
            description=f"🎁 **獎品：**{lottery['prize']}",
            color=0x00FF88,
            timestamp=datetime.now(),
        )

        winner_text = "\n".join(
            f"　🏆 **{i+1}.** {w.mention}" for i, w in enumerate(winners)
        )
        result_embed.add_field(name="🥇 中獎者", value=winner_text, inline=False)

        not_selected = [m for m in participants if m not in winners]
        if not_selected:
            others_text = ", ".join(m.display_name for m in not_selected)
            result_embed.add_field(
                name="😢 未中獎", value=others_text[:1024], inline=False
            )

        result_embed.add_field(
            name="📊 統計",
            value=f"參加人數：{len(participants)} 人\n中獎人數：{winner_count} 人",
            inline=False,
        )
        result_embed.set_footer(text=f"由 {interaction.user.display_name} 開獎")

        await msg.edit(embed=result_embed)

        # 同時 @中獎者
        mentions = " ".join(w.mention for w in winners)
        await interaction.channel.send(f"🎊 恭喜中獎：{mentions}！")

        # 清除此抽獎
        del active_lotteries[self.guild_id][self.lottery_key]

    @ui.button(label="👀 查看名單", style=discord.ButtonStyle.primary, row=2)
    async def view_button(self, interaction: discord.Interaction, button: ui.Button):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message("❌ 找不到此抽獎活動！", ephemeral=True)
            return

        participants = lottery["participants"]
        if not participants:
            await interaction.response.send_message("📋 目前尚無指定成員。", ephemeral=True)
            return

        member_list = "\n".join(
            f"　`{i+1}.` {m.display_name} (`{m.id}`)"
            for i, m in enumerate(participants)
        )
        embed = discord.Embed(
            title=f"📋 {lottery['name']} — 參加名單",
            description=member_list[:4096],
            color=0x5865F2,
        )
        embed.set_footer(text=f"共 {len(participants)} 人")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="🗑️ 清空名單", style=discord.ButtonStyle.danger, row=2)
    async def clear_button(self, interaction: discord.Interaction, button: ui.Button):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message("❌ 找不到此抽獎活動！", ephemeral=True)
            return

        if interaction.user.id != lottery["creator"]:
            await interaction.response.send_message("❌ 只有建立者可以清空名單！", ephemeral=True)
            return

        lottery["participants"] = []

        # 更新 embed
        embed = interaction.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if "已指定成員" in field.name:
                embed.set_field_at(
                    i, name="📋 已指定成員", value="尚未指定任何成員", inline=False
                )
                break

        await interaction.response.edit_message(embed=embed)

    @ui.button(label="❌ 取消抽獎", style=discord.ButtonStyle.secondary, row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message("❌ 找不到此抽獎活動！", ephemeral=True)
            return

        if interaction.user.id != lottery["creator"]:
            await interaction.response.send_message("❌ 只有建立者可以取消！", ephemeral=True)
            return

        del active_lotteries[self.guild_id][self.lottery_key]

        embed = discord.Embed(
            title="❌ 抽獎已取消",
            description=f"「{lottery['name']}」已被 {interaction.user.display_name} 取消。",
            color=0xFF0000,
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================================
#  主控制面板 Embed + View
# ============================================================
class MainPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="🎰 建立抽獎", style=discord.ButtonStyle.success, row=0)
    async def create_lottery(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(LotteryModal())

    @ui.button(label="📋 查看進行中", style=discord.ButtonStyle.primary, row=0)
    async def view_active(self, interaction: discord.Interaction, button: ui.Button):
        guild_id = interaction.guild_id
        lotteries = active_lotteries.get(guild_id, {})

        if not lotteries:
            await interaction.response.send_message("📭 目前沒有進行中的抽獎活動。", ephemeral=True)
            return

        embed = discord.Embed(title="📋 進行中的抽獎活動", color=0x5865F2)
        for key, lottery in lotteries.items():
            embed.add_field(
                name=f"🎰 {lottery['name']}",
                value=(
                    f"🎁 獎品：{lottery['prize']}\n"
                    f"👥 中獎人數：{lottery['winner_count']}\n"
                    f"📝 已指定：{len(lottery['participants'])} 人"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="❓ 使用說明", style=discord.ButtonStyle.secondary, row=0)
    async def help_btn(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="📖 抽獎機器人使用說明",
            color=0xFFD700,
        )
        embed.add_field(
            name="🔹 /抽獎面板",
            value="顯示主控制面板（就是這個面板）",
            inline=False,
        )
        embed.add_field(
            name="🔹 /建立抽獎",
            value="透過表單建立新的抽獎活動",
            inline=False,
        )
        embed.add_field(
            name="🔹 /快速抽獎",
            value="快速指定成員並立刻抽獎\n用法：`/快速抽獎 中獎人數:3 成員:@A @B @C @D @E`",
            inline=False,
        )
        embed.add_field(
            name="🔹 流程說明",
            value=(
                "1️⃣ 點「建立抽獎」填寫表單\n"
                "2️⃣ 用下拉選單選擇參加成員\n"
                "3️⃣ 點「開始抽獎」抽出中獎者"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
#  斜線指令 (Slash Commands)
# ============================================================
@bot.tree.command(name="抽獎面板", description="📊 顯示抽獎機器人控制面板")
async def lottery_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎰 抽獎機器人控制台",
        description=(
            "歡迎使用抽獎機器人！\n"
            "點擊下方按鈕開始操作。\n"
            "━━━━━━━━━━━━━━━━━━━━"
        ),
        color=0xFFD700,
    )
    embed.add_field(
        name="🎰 建立抽獎",
        value="建立新的抽獎活動",
        inline=True,
    )
    embed.add_field(
        name="📋 查看進行中",
        value="查看目前的抽獎",
        inline=True,
    )
    embed.add_field(
        name="❓ 使用說明",
        value="查看指令教學",
        inline=True,
    )
    embed.set_footer(text="抽獎機器人 v1.0 ｜ 公平公正公開 🎲")

    await interaction.response.send_message(embed=embed, view=MainPanelView())


@bot.tree.command(name="建立抽獎", description="📝 透過表單建立一個新的抽獎活動")
async def create_lottery_cmd(interaction: discord.Interaction):
    await interaction.response.send_modal(LotteryModal())


@bot.tree.command(name="快速抽獎", description="⚡ 從指定成員中快速抽獎")
@app_commands.describe(
    中獎人數="要抽出幾位中獎者",
    獎品="獎品說明",
    成員1="參加者 1",
    成員2="參加者 2",
    成員3="參加者 3",
    成員4="參加者 4（選填）",
    成員5="參加者 5（選填）",
    成員6="參加者 6（選填）",
    成員7="參加者 7（選填）",
    成員8="參加者 8（選填）",
)
async def quick_draw(
    interaction: discord.Interaction,
    中獎人數: int,
    獎品: str,
    成員1: discord.Member,
    成員2: discord.Member,
    成員3: discord.Member,
    成員4: Optional[discord.Member] = None,
    成員5: Optional[discord.Member] = None,
    成員6: Optional[discord.Member] = None,
    成員7: Optional[discord.Member] = None,
    成員8: Optional[discord.Member] = None,
):
    # 收集所有成員（去重、排除 bot）
    all_members = [成員1, 成員2, 成員3, 成員4, 成員5, 成員6, 成員7, 成員8]
    participants = list({m for m in all_members if m is not None and not m.bot})

    if 中獎人數 < 1:
        await interaction.response.send_message("❌ 中獎人數至少為 1！", ephemeral=True)
        return

    if len(participants) < 中獎人數:
        await interaction.response.send_message(
            f"❌ 參加人數（{len(participants)}）不足，無法抽出 {中獎人數} 位中獎者！",
            ephemeral=True,
        )
        return

    # 倒數
    await interaction.response.defer()
    countdown_embed = discord.Embed(title="⚡ 快速抽獎即將開始...", color=0xFF6B6B)
    msg = await interaction.followup.send(embed=countdown_embed)

    for i in [3, 2, 1]:
        countdown_embed.description = f"# {i}"
        await msg.edit(embed=countdown_embed)
        await asyncio.sleep(1)

    # 抽獎
    winners = random.sample(participants, 中獎人數)

    result_embed = discord.Embed(
        title="🎉 快速抽獎結果",
        description=f"🎁 **獎品：**{獎品}",
        color=0x00FF88,
        timestamp=datetime.now(),
    )

    winner_text = "\n".join(f"　🏆 **{i+1}.** {w.mention}" for i, w in enumerate(winners))
    result_embed.add_field(name="🥇 中獎者", value=winner_text, inline=False)

    participant_text = ", ".join(m.display_name for m in participants)
    result_embed.add_field(
        name="📊 參加名單",
        value=f"{participant_text}\n（共 {len(participants)} 人，抽 {中獎人數} 人）",
        inline=False,
    )
    result_embed.set_footer(text=f"由 {interaction.user.display_name} 開獎")

    await msg.edit(embed=result_embed)
    mentions = " ".join(w.mention for w in winners)
    await interaction.channel.send(f"🎊 恭喜中獎：{mentions}！")


# ============================================================
#  啟動 Bot
# ============================================================
if __name__ == "__main__":
    print("🚀 正在啟動抽獎機器人...")
    bot.run(BOT_TOKEN)
