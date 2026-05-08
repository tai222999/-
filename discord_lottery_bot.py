"""
🎰 Discord 抽獎機器人 v2.0
新功能：
  - 控制面板與建立視窗只有建立者看得到（ephemeral）
  - 可設定台灣時間定時開獎
  - 支援：指定成員 / 頻道全員 / 指定身分組 抽獎

部署平台：Render / Railway
"""

import os
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import random
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

# ============================================================
#  台灣時區 (UTC+8)
# ============================================================
TW_TZ = timezone(timedelta(hours=8))

def tw_now():
    return datetime.now(TW_TZ)

# ============================================================
#  從環境變數讀取 Token
# ============================================================
BOT_TOKEN = os.environ.get("DISCORD_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ 請在環境變數中設定 DISCORD_TOKEN")

# ============================================================
#  Bot 初始化
# ============================================================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 儲存進行中的抽獎 { guild_id: { lottery_key: {...} } }
active_lotteries = {}
# 儲存定時抽獎任務 { "guild_id-lottery_key": {...} }
scheduled_tasks = {}


# ============================================================
#  定時開獎檢查（每 30 秒檢查一次）
# ============================================================
@tasks.loop(seconds=30)
async def check_scheduled_lotteries():
    now = tw_now()
    to_remove = []

    for task_key, task_info in list(scheduled_tasks.items()):
        if now >= task_info["draw_time"]:
            to_remove.append(task_key)
            guild_id = task_info["guild_id"]
            lottery_key = task_info["lottery_key"]
            channel_id = task_info["channel_id"]

            lottery = active_lotteries.get(guild_id, {}).get(lottery_key)
            if not lottery:
                continue

            channel = bot.get_channel(channel_id)
            if not channel:
                continue

            participants = lottery["participants"]
            winner_count = lottery["winner_count"]

            if len(participants) < winner_count:
                await channel.send(
                    f"❌ 定時抽獎「{lottery['name']}」因參加人數不足（{len(participants)}/{winner_count}）已取消。"
                )
                if lottery_key in active_lotteries.get(guild_id, {}):
                    del active_lotteries[guild_id][lottery_key]
                continue

            # 開獎動畫
            countdown_embed = discord.Embed(
                title=f"⏰ 定時抽獎開始：{lottery['name']}", color=0xFF6B6B
            )
            msg = await channel.send(embed=countdown_embed)

            for i in [3, 2, 1]:
                countdown_embed.description = f"# {i}"
                await msg.edit(embed=countdown_embed)
                await asyncio.sleep(1)

            winners = random.sample(participants, winner_count)

            result_embed = discord.Embed(
                title=f"🎉 抽獎結果：{lottery['name']}",
                description=f"🎁 **獎品：**{lottery['prize']}",
                color=0x00FF88,
                timestamp=tw_now(),
            )
            winner_text = "\n".join(
                f"　🏆 **{i+1}.** {w.mention}" for i, w in enumerate(winners)
            )
            result_embed.add_field(name="🥇 中獎者", value=winner_text, inline=False)

            not_selected = [m for m in participants if m not in winners]
            if not_selected:
                others = ", ".join(m.display_name for m in not_selected)
                result_embed.add_field(name="😢 未中獎", value=others[:1024], inline=False)

            result_embed.add_field(
                name="📊 統計",
                value=f"參加人數：{len(participants)} 人\n中獎人數：{winner_count} 人",
                inline=False,
            )
            result_embed.set_footer(text="⏰ 定時自動開獎")
            await msg.edit(embed=result_embed)

            mentions = " ".join(w.mention for w in winners)
            await channel.send(f"🎊 恭喜中獎：{mentions}！")

            if lottery_key in active_lotteries.get(guild_id, {}):
                del active_lotteries[guild_id][lottery_key]

    for key in to_remove:
        if key in scheduled_tasks:
            del scheduled_tasks[key]


# ============================================================
#  Bot 上線
# ============================================================
@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        print("✅ 指令同步完成")
    except Exception as e:
        print(f"⚠️ 指令同步失敗：{e}")
    print(f"✅ 機器人已上線：{bot.user}")
    print(f"📡 已加入 {len(bot.guilds)} 個伺服器")
    if not check_scheduled_lotteries.is_running():
        check_scheduled_lotteries.start()


# 全域錯誤處理（避免 Unknown interaction 噴紅字）
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandInvokeError):
        original = error.original
        if isinstance(original, discord.NotFound) and original.code == 10062:
            # Unknown interaction — 通常是部署重啟造成的，可忽略
            print(f"⚠️ Interaction 已過期（指令：{interaction.command.name}），已忽略")
            return
    # 其他錯誤嘗試回報給使用者
    try:
        if interaction.response.is_done():
            await interaction.followup.send(f"❌ 發生錯誤：{error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ 發生錯誤：{error}", ephemeral=True)
    except Exception:
        print(f"❌ 無法回報錯誤：{error}")


# ============================================================
#  建立抽獎表單 Modal（新增定時欄位）
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
    schedule_time = ui.TextInput(
        label="定時開獎（台灣時間，選填）",
        placeholder="格式：2025-01-15 20:00（留空＝手動開獎）",
        required=False,
        max_length=20,
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

        # 驗證定時時間
        draw_time = None
        if self.schedule_time.value.strip():
            try:
                draw_time = datetime.strptime(
                    self.schedule_time.value.strip(), "%Y-%m-%d %H:%M"
                ).replace(tzinfo=TW_TZ)
                if draw_time <= tw_now():
                    await interaction.response.send_message(
                        "❌ 定時時間必須是未來的時間！", ephemeral=True
                    )
                    return
            except ValueError:
                await interaction.response.send_message(
                    "❌ 時間格式錯誤！請用：`2025-01-15 20:00`", ephemeral=True
                )
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
            "participants": [],
            "creator": interaction.user.id,
            "created_at": tw_now(),
            "draw_time": draw_time,
            "channel_id": interaction.channel_id,
        }

        # 如果有定時，加入排程
        if draw_time:
            task_key = f"{guild_id}-{lottery_key}"
            scheduled_tasks[task_key] = {
                "guild_id": guild_id,
                "lottery_key": lottery_key,
                "channel_id": interaction.channel_id,
                "draw_time": draw_time,
            }

        # ── 公開公告（所有人看得到）──
        time_str = draw_time.strftime("%Y-%m-%d %H:%M") if draw_time else "手動開獎"
        public_embed = discord.Embed(
            title=f"🎰 抽獎活動公告：{self.lottery_name.value}",
            description="🔔 以下抽獎活動已建立，請留意開獎時間！",
            color=0xFF9500,
        )
        public_embed.add_field(name="🎁 獎品", value=self.prize.value, inline=True)
        public_embed.add_field(name="👥 中獎人數", value=f"{count} 人", inline=True)
        public_embed.add_field(name="⏰ 開獎時間", value=time_str, inline=True)
        if self.description.value:
            public_embed.add_field(name="📝 說明", value=self.description.value, inline=False)
        public_embed.set_footer(text=f"建立者：{interaction.user.display_name}｜抽獎機器人 v2.0")

        # ── 私人管理面板（只有建立者看得到）──
        manage_embed = discord.Embed(
            title=f"🔧 管理面板：{self.lottery_name.value}",
            description="⬇️ 以下操作僅你可見，其他成員看不到。",
            color=0xFFD700,
        )
        manage_embed.add_field(name="🎁 獎品", value=self.prize.value, inline=True)
        manage_embed.add_field(name="👥 中獎人數", value=f"{count} 人", inline=True)
        manage_embed.add_field(name="⏰ 開獎時間", value=time_str, inline=True)
        manage_embed.add_field(name="📋 已指定成員", value="尚未指定任何成員", inline=False)
        manage_embed.set_footer(text=f"建立者：{interaction.user.display_name}｜僅你可見")

        view = LotteryManageView(lottery_key, guild_id)

        # 先回應 interaction（私人管理面板）
        await interaction.response.send_message(embed=manage_embed, view=view, ephemeral=True)
        # 再公開發送公告到頻道
        await interaction.channel.send(embed=public_embed)


# ============================================================
#  成員選擇下拉選單（手動選人）
# ============================================================
class MemberSelect(ui.UserSelect):
    def __init__(self, lottery_key: str, guild_id: int):
        super().__init__(
            placeholder="👤 手動選擇成員...",
            min_values=1,
            max_values=25,
            row=0,
        )
        self.lottery_key = lottery_key
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message("❌ 找不到此抽獎活動！", ephemeral=True)
            return

        if interaction.user.id != lottery["creator"]:
            await interaction.response.send_message("❌ 只有建立者可以操作！", ephemeral=True)
            return

        existing_ids = {m.id for m in lottery["participants"]}
        added = []
        for member in self.values:
            if member.id not in existing_ids and not member.bot:
                lottery["participants"].append(member)
                added.append(member.display_name)

        if added:
            await _update_member_embed(interaction, lottery)
        else:
            await interaction.response.send_message(
                "⚠️ 所選成員已在名單中，或是機器人不可參加。", ephemeral=True
            )


# ============================================================
#  身分組選擇下拉選單（選身分組 → 整組加入）
# ============================================================
class RoleSelect(ui.RoleSelect):
    def __init__(self, lottery_key: str, guild_id: int):
        super().__init__(
            placeholder="🏷️ 選擇身分組（整組加入抽獎）...",
            min_values=1,
            max_values=10,
            row=1,
        )
        self.lottery_key = lottery_key
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message("❌ 找不到此抽獎活動！", ephemeral=True)
            return

        if interaction.user.id != lottery["creator"]:
            await interaction.response.send_message("❌ 只有建立者可以操作！", ephemeral=True)
            return

        existing_ids = {m.id for m in lottery["participants"]}
        added = []
        for role in self.values:
            for member in role.members:
                if member.id not in existing_ids and not member.bot:
                    lottery["participants"].append(member)
                    existing_ids.add(member.id)
                    added.append(member.display_name)

        if added:
            await _update_member_embed(interaction, lottery)
        else:
            await interaction.response.send_message(
                "⚠️ 該身分組的成員都已在名單中。", ephemeral=True
            )


# ============================================================
#  更新 Embed 的成員列表（共用函數）
# ============================================================
async def _update_member_embed(interaction: discord.Interaction, lottery: dict):
    total = len(lottery["participants"])
    if total <= 30:
        member_list = "\n".join(
            f"　`{i+1}.` {m.display_name}"
            for i, m in enumerate(lottery["participants"])
        )
    else:
        # 超過 30 人只顯示前 10 + 後 5
        first = "\n".join(
            f"　`{i+1}.` {m.display_name}"
            for i, m in enumerate(lottery["participants"][:10])
        )
        last = "\n".join(
            f"　`{i+1}.` {m.display_name}"
            for i, m in enumerate(lottery["participants"][-5:], total - 4)
        )
        member_list = f"{first}\n　... 共 {total} 人 ...\n{last}"

    embed = interaction.message.embeds[0]
    for i, field in enumerate(embed.fields):
        if "已指定成員" in field.name:
            embed.set_field_at(
                i,
                name=f"📋 已指定成員（共 {total} 人）",
                value=member_list[:1024],
                inline=False,
            )
            break
    await interaction.response.edit_message(embed=embed)


# ============================================================
#  抽獎管理面板（按鈕 + 選單）
# ============================================================
class LotteryManageView(ui.View):
    def __init__(self, lottery_key: str, guild_id: int):
        super().__init__(timeout=None)
        self.lottery_key = lottery_key
        self.guild_id = guild_id

        # Row 0: 手動選人
        self.add_item(MemberSelect(lottery_key, guild_id))
        # Row 1: 選身分組
        self.add_item(RoleSelect(lottery_key, guild_id))

    # ── 加入頻道全員 ──
    @ui.button(label="📢 加入頻道全員", style=discord.ButtonStyle.primary, row=2)
    async def add_channel_members(self, interaction: discord.Interaction, button: ui.Button):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message("❌ 找不到此抽獎活動！", ephemeral=True)
            return

        if interaction.user.id != lottery["creator"]:
            await interaction.response.send_message("❌ 只有建立者可以操作！", ephemeral=True)
            return

        channel = interaction.channel
        existing_ids = {m.id for m in lottery["participants"]}
        added = 0

        for member in channel.members:
            if member.id not in existing_ids and not member.bot:
                lottery["participants"].append(member)
                existing_ids.add(member.id)
                added += 1

        if added > 0:
            await _update_member_embed(interaction, lottery)
        else:
            await interaction.response.send_message(
                "⚠️ 頻道內所有成員都已在名單中。", ephemeral=True
            )

    # ── 開始抽獎 ──
    @ui.button(label="🎲 開始抽獎", style=discord.ButtonStyle.success, row=3)
    async def draw_button(self, interaction: discord.Interaction, button: ui.Button):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message("❌ 找不到此抽獎活動！", ephemeral=True)
            return

        if interaction.user.id != lottery["creator"]:
            await interaction.response.send_message("❌ 只有建立者可以開獎！", ephemeral=True)
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

        # 先回應 ephemeral 告知建立者
        await interaction.response.send_message("🎲 正在開獎中...", ephemeral=True)

        # 在頻道公開發送倒數（所有人看得到）
        channel = interaction.channel
        countdown_embed = discord.Embed(
            title=f"🎰 抽獎即將開始：{lottery['name']}", color=0xFF6B6B
        )
        msg = await channel.send(embed=countdown_embed)

        for i in [3, 2, 1]:
            countdown_embed.description = f"# {i}"
            await msg.edit(embed=countdown_embed)
            await asyncio.sleep(1)

        winners = random.sample(participants, winner_count)

        result_embed = discord.Embed(
            title=f"🎉 抽獎結果：{lottery['name']}",
            description=f"🎁 **獎品：**{lottery['prize']}",
            color=0x00FF88,
            timestamp=tw_now(),
        )

        winner_text = "\n".join(
            f"　🏆 **{i+1}.** {w.mention}" for i, w in enumerate(winners)
        )
        result_embed.add_field(name="🥇 中獎者", value=winner_text, inline=False)

        not_selected = [m for m in participants if m not in winners]
        if not_selected:
            others = ", ".join(m.display_name for m in not_selected)
            result_embed.add_field(name="😢 未中獎", value=others[:1024], inline=False)

        result_embed.add_field(
            name="📊 統計",
            value=f"參加人數：{len(participants)} 人\n中獎人數：{winner_count} 人",
            inline=False,
        )
        result_embed.set_footer(text=f"由 {interaction.user.display_name} 開獎")

        await msg.edit(embed=result_embed)
        mentions = " ".join(w.mention for w in winners)
        await channel.send(f"🎊 恭喜中獎：{mentions}！")

        # 清除定時任務
        task_key = f"{self.guild_id}-{self.lottery_key}"
        if task_key in scheduled_tasks:
            del scheduled_tasks[task_key]

        del active_lotteries[self.guild_id][self.lottery_key]

    # ── 查看名單 ──
    @ui.button(label="👀 查看名單", style=discord.ButtonStyle.secondary, row=3)
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

    # ── 清空名單 ──
    @ui.button(label="🗑️ 清空名單", style=discord.ButtonStyle.danger, row=4)
    async def clear_button(self, interaction: discord.Interaction, button: ui.Button):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message("❌ 找不到此抽獎活動！", ephemeral=True)
            return

        if interaction.user.id != lottery["creator"]:
            await interaction.response.send_message("❌ 只有建立者可以清空名單！", ephemeral=True)
            return

        lottery["participants"] = []
        embed = interaction.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if "已指定成員" in field.name:
                embed.set_field_at(
                    i, name="📋 已指定成員", value="尚未指定任何成員", inline=False
                )
                break
        await interaction.response.edit_message(embed=embed)

    # ── 取消抽獎 ──
    @ui.button(label="❌ 取消抽獎", style=discord.ButtonStyle.secondary, row=4)
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        lottery = active_lotteries.get(self.guild_id, {}).get(self.lottery_key)
        if not lottery:
            await interaction.response.send_message("❌ 找不到此抽獎活動！", ephemeral=True)
            return

        if interaction.user.id != lottery["creator"]:
            await interaction.response.send_message("❌ 只有建立者可以取消！", ephemeral=True)
            return

        # 清除定時
        task_key = f"{self.guild_id}-{self.lottery_key}"
        if task_key in scheduled_tasks:
            del scheduled_tasks[task_key]

        del active_lotteries[self.guild_id][self.lottery_key]

        embed = discord.Embed(
            title="❌ 抽獎已取消",
            description=f"「{lottery['name']}」已被 {interaction.user.display_name} 取消。",
            color=0xFF0000,
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ============================================================
#  主控制面板
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
            time_str = (
                lottery["draw_time"].strftime("%Y-%m-%d %H:%M")
                if lottery.get("draw_time")
                else "手動開獎"
            )
            embed.add_field(
                name=f"🎰 {lottery['name']}",
                value=(
                    f"🎁 獎品：{lottery['prize']}\n"
                    f"👥 中獎人數：{lottery['winner_count']}\n"
                    f"📝 已指定：{len(lottery['participants'])} 人\n"
                    f"⏰ 開獎：{time_str}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="❓ 使用說明", style=discord.ButtonStyle.secondary, row=0)
    async def help_btn(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(title="📖 抽獎機器人 v2.0 使用說明", color=0xFFD700)
        embed.add_field(
            name="🔹 /抽獎面板",
            value="顯示主控制面板（僅你可見）",
            inline=False,
        )
        embed.add_field(
            name="🔹 /建立抽獎",
            value="填寫表單建立抽獎（可設定時開獎）",
            inline=False,
        )
        embed.add_field(
            name="🔹 /快速抽獎",
            value="直接指定成員立刻開獎",
            inline=False,
        )
        embed.add_field(
            name="🔹 抽獎對象（三種方式）",
            value=(
                "👤 **手動選人** — 用下拉選單逐一選\n"
                "🏷️ **選身分組** — 整個身分組加入\n"
                "📢 **頻道全員** — 看得到此頻道的人全加入"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔹 定時開獎",
            value=(
                "建立時填入台灣時間\n"
                "格式：`2025-06-01 20:00`\n"
                "時間到自動在頻道開獎"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
#  斜線指令
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
    embed.add_field(name="🎰 建立抽獎", value="建立新的抽獎活動", inline=True)
    embed.add_field(name="📋 查看進行中", value="查看目前的抽獎", inline=True)
    embed.add_field(name="❓ 使用說明", value="查看指令教學", inline=True)
    embed.set_footer(text="抽獎機器人 v2.0 ｜ 公平公正公開 🎲")

    # ✅ 只有你看得到
    await interaction.response.send_message(embed=embed, view=MainPanelView(), ephemeral=True)


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

    await interaction.response.defer()
    countdown_embed = discord.Embed(title="⚡ 快速抽獎即將開始...", color=0xFF6B6B)
    msg = await interaction.followup.send(embed=countdown_embed)

    for i in [3, 2, 1]:
        countdown_embed.description = f"# {i}"
        await msg.edit(embed=countdown_embed)
        await asyncio.sleep(1)

    winners = random.sample(participants, 中獎人數)

    result_embed = discord.Embed(
        title="🎉 快速抽獎結果",
        description=f"🎁 **獎品：**{獎品}",
        color=0x00FF88,
        timestamp=tw_now(),
    )
    winner_text = "\n".join(
        f"　🏆 **{i+1}.** {w.mention}" for i, w in enumerate(winners)
    )
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
#  啟動
# ============================================================
if __name__ == "__main__":
    print("🚀 正在啟動抽獎機器人 v2.0...")
    bot.run(BOT_TOKEN)