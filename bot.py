# TRANSACTION BOT, Improved Edition
import discord
import json
import os
import asyncio
import re
import random
from dotenv import load_dotenv
load_dotenv()
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Select, View
from typing import Optional
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


# ── Server & Role IDs ─────────────────────────────────────────────────────────
Server_id = discord.Object(id=1529602214518194246)

Commentator_role = None
Referee_role     = 1529607759262126140
Caster_role      = None
team_player_role = 1529660833850851328
staff_role       = None
captain_role     = 1529608315091423435
co_captain_role  = 1529608375619289088

# ── Channel IDs ───────────────────────────────────────────────────────────────
Transaction_channel  = 1530371693183238306
Audit_log_channel    = 1530371748212510761
Scrims_channel       = 1530372170453352639
Scrim_score_channel  = 1530372192410402886
Officials_channel    = 1530372260328898641

# ── Data paths ────────────────────────────────────────────────────────────────
Data_Railway = os.getenv("Data_Railway", "/data")
os.makedirs(Data_Railway, exist_ok=True)
Team_file            = os.path.join(Data_Railway, "teams.json")
Scrim_file           = os.path.join(Data_Railway, "scrims.json")
Scrim_message_file   = os.path.join(Data_Railway, "scrim_messages.json")
Invite_file          = os.path.join(Data_Railway, "invites.json")
Seeding_file         = os.path.join(Data_Railway, "seeding.json")
Scrim_channel_file   = os.path.join(Data_Railway, "scrim_channels.json")
Player_history_file  = os.path.join(Data_Railway, "player_history.json")
Proposals_file       = os.path.join(Data_Railway, "proposals.json")

# ── Premium ───────────────────────────────────────────────────────────────────
Paid_for_premium = {Server_id.id}
Premium_enabled  = Server_id.id in Paid_for_premium
print("Premium features enabled." if Premium_enabled else "Premium features are not enabled.")

# ── Locks ─────────────────────────────────────────────────────────────────────
teams_lock   = asyncio.Lock()
seeding_lock = asyncio.Lock()
scrims_lock  = asyncio.Lock()

# ── Timezone ──────────────────────────────────────────────────────────────────
# All scrim times are assumed to be in this timezone unless you set the env var.
SERVER_TIMEZONE = ZoneInfo(os.getenv("SERVER_TIMEZONE", "America/New_York"))

# ── Reminder timing (minutes before scrim start) ──────────────────────────────
TEAM_PING_MINUTES = 20   # team channel ping
OFFICIAL_DM_MINUTES = 15  # referee/caster code DM + open-call

# ── Validation helpers ────────────────────────────────────────────────────────
TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s*(AM|PM|am|pm)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}/\d{1,2}/\d{4}$|^[A-Za-z]+ \d{1,2}(st|nd|rd|th)?,? \d{4}$")

def validate_time(t: str) -> bool:
    return bool(TIME_RE.match(t.strip()))

def validate_date(d: str) -> bool:
    return bool(DATE_RE.match(d.strip()))

MAX_SCORE = 999


def parse_scrim_datetime(time_str: str, date_str: str) -> Optional[str]:
    if not validate_time(time_str) or not validate_date(date_str):
        return None

    date_clean = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", date_str.strip(), flags=re.IGNORECASE)
    date_clean = date_clean.replace(",", "")

    parsed_date = None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d %Y"):
        try:
            parsed_date = datetime.strptime(date_clean, fmt).date()
            break
        except ValueError:
            continue
    if parsed_date is None:
        return None

    time_clean = time_str.strip().upper().replace(" ", "")
    parsed_time = None
    for fmt in ("%I:%M%p", "%H:%M"):
        try:
            parsed_time = datetime.strptime(time_clean, fmt).time()
            break
        except ValueError:
            continue
    if parsed_time is None:
        return None

    local_dt = datetime.combine(parsed_date, parsed_time, tzinfo=SERVER_TIMEZONE)
    return local_dt.astimezone(timezone.utc).isoformat()


# ── JSON helpers ──────────────────────────────────────────────────────────────
def load_json_file(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        content = f.read().strip()
        return json.loads(content) if content else default

def save_json_file(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

def load_teams() -> dict:
    data = load_json_file(Team_file, {})
    return {k.lower(): v for k, v in data.items()}

def save_teams(data: dict):           save_json_file(Team_file, data)
def load_seeding() -> dict:           return load_json_file(Seeding_file, {})
def save_seeding(data: dict):         save_json_file(Seeding_file, data)
def load_scrims() -> list:
    data = load_json_file(Scrim_file, [])
    return data if isinstance(data, list) else []
def save_scrims(data: list):          save_json_file(Scrim_file, data)
def load_scrim_messages() -> dict:    return load_json_file(Scrim_message_file, {})
def save_scrim_messages(data: dict):  save_json_file(Scrim_message_file, data)
def load_proposals() -> dict:         return load_json_file(Proposals_file, {})
def save_proposals(data: dict):       save_json_file(Proposals_file, data)

def load_scrim_channels() -> dict:
    data = load_json_file(Scrim_channel_file, {})
    return {int(k): v for k, v in data.items()}

def save_scrim_channels(data: dict):
    save_json_file(Scrim_channel_file, {str(k): v for k, v in data.items()})

def save_invites(data: dict):
    save_json_file(Invite_file, {str(k): v for k, v in data.items()})

def load_invites() -> dict:
    data = load_json_file(Invite_file, {})
    return {int(k): v for k, v in data.items()}

def load_player_history() -> dict:    return load_json_file(Player_history_file, {})
def save_player_history(data: dict):  save_json_file(Player_history_file, data)

# ── In-memory state ───────────────────────────────────────────────────────────
teams:             dict = load_teams()
seeding:           dict = load_seeding()
scrims_schedule:   list = load_scrims()
scrim_message_ids: dict = load_scrim_messages()
scrim_messages:    dict = {}
scrim_channels:    dict = load_scrim_channels()
pending_invites:   dict = load_invites()
player_history:    dict = load_player_history()
pending_proposals: dict = load_proposals() 

# ── Bot class ─────────────────────────────────────────────────────────────────
class Had3sBot(commands.Bot):
    async def on_ready(self):
        print(f'{self.user} is now online')
        self.add_view(ScrimThingy())
        for key, data in pending_proposals.items():
            self.add_view(ScrimProposalView(
                data["t1_key"], data["t2_key"],
                data["time"], data["date"],
                data["proposer_id"], data["other_captain_id"],
                proposal_key=key))
        try:
            synced = await self.tree.sync(guild=Server_id)
            print(f'{len(synced)} commands synced to {Server_id.id}.')
        except Exception as e:
            print(f'Sync error: {e}')
        if not scrim_reminder.is_running():
            scrim_reminder.start()

intents                 = discord.Intents.default()
intents.members         = True
intents.message_content = True
had3sbot          = Had3sBot(command_prefix="!", intents=intents)

# ── Helper: resolve team_player_role int to Role object ──────────────────────
def get_tpr(guild: discord.Guild) -> discord.Role | None:
    return guild.get_role(team_player_role)

# ── Staff check ────────────────────────────────────────────────────────────────
def is_staff_member(member: discord.Member) -> bool:
    """Staff (staff_role) are not permitted to be on a competing team."""
    return any(r.id == staff_role for r in member.roles)

# ── General Captain / Co-Captain role helpers ────────────────────────────────
def is_captain_anywhere(player_id: int, exclude_team: str | None = None) -> bool:
    """True if player_id is captain of any team other than exclude_team."""
    for name, t in teams.items():
        if name == exclude_team:
            continue
        if t.get("captain") == player_id:
            return True
    return False

def is_cocaptain_anywhere(player_id: int, exclude_team: str | None = None) -> bool:
    """True if player_id is co-captain of any team other than exclude_team."""
    for name, t in teams.items():
        if name == exclude_team:
            continue
        if t.get("co_captain") == player_id:
            return True
    return False

async def grant_general_captain(guild: discord.Guild, player_id: int):
    role = guild.get_role(captain_role)
    member = guild.get_member(player_id)
    if role and member and role not in member.roles:
        try:
            await member.add_roles(role)
        except Exception:
            pass

async def grant_general_cocaptain(guild: discord.Guild, player_id: int):
    role = guild.get_role(co_captain_role)
    member = guild.get_member(player_id)
    if role and member and role not in member.roles:
        try:
            await member.add_roles(role)
        except Exception:
            pass

async def revoke_general_captain_if_unneeded(guild: discord.Guild, player_id: int, exclude_team: str | None = None):
    """Remove the general Captain role unless the player is still captain of another team."""
    if is_captain_anywhere(player_id, exclude_team=exclude_team):
        return
    role = guild.get_role(captain_role)
    member = guild.get_member(player_id)
    if role and member and role in member.roles:
        try:
            await member.remove_roles(role)
        except Exception:
            pass

async def revoke_general_cocaptain_if_unneeded(guild: discord.Guild, player_id: int, exclude_team: str | None = None):
    """Remove the general Co-Captain role unless the player is still co-captain of another team."""
    if is_cocaptain_anywhere(player_id, exclude_team=exclude_team):
        return
    role = guild.get_role(co_captain_role)
    member = guild.get_member(player_id)
    if role and member and role in member.roles:
        try:
            await member.remove_roles(role)
        except Exception:
            pass

# ── Premium check ─────────────────────────────────────────────────────────────
def is_premium():
    async def paid_premium(interaction: discord.Interaction):
        if interaction.guild and interaction.guild.id in Paid_for_premium:
            return True
        await interaction.response.send_message(
            "This server has not paid for premium. Contact <@1352754619633242112>.", ephemeral=True)
        return False
    return app_commands.check(paid_premium)



async def log_command(interaction: discord.Interaction) -> bool:
    if interaction.command is None:                                       return True
    if interaction.type == discord.InteractionType.autocomplete:          return True
    if not interaction.guild or interaction.guild.id not in Paid_for_premium: return True
    channel = interaction.guild.get_channel(Audit_log_channel)
    if channel:
        options = interaction.data.get("options", [])
        parts   = []
        for opt in options:
            val = f"<@{opt['value']}>" if opt["name"] == "player" else opt["value"]
            parts.append(f"{opt['name']}: `{val}`")
        embed = discord.Embed(
            description=f"**/{interaction.command.name}**" + (f"\n{' '.join(parts)}" if parts else ""))
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()
        await channel.send(embed=embed)
    return True

had3sbot.tree.interaction_check = log_command


reminded_scrims:    set = set()   # team ping fired
official_dm_scrims: set = set()   # referee/caster dm or open-call fired
code_sent_scrims:   set = set()   # code posted at start time

MENTION_RE = re.compile(r"<@!?(\d+)>")

@tasks.loop(minutes=1)
async def scrim_reminder():
    guild = had3sbot.get_guild(Server_id.id)
    if not guild:
        return
    now = datetime.now(timezone.utc)

    for scrim in scrims_schedule:
        dt_str = scrim.get("datetime_utc")
        if not dt_str:
            continue
        try:
            scrim_dt = datetime.fromisoformat(dt_str)
        except ValueError:
            continue

        delta    = scrim_dt - now
        scrim_id = f"{scrim['team1']}|{scrim['team2']}"
        league_code = scrim.get("league_code", f"SCL{random.randint(100, 999)}")

        t1_key = scrim["team1"].lower()
        t2_key = scrim["team2"].lower()
        t1     = teams.get(t1_key, {})
        t2     = teams.get(t2_key, {})

        # Computed unconditionally so all stages below can safely use it.
        r1        = guild.get_role(t1.get("team_role")) if t1 else None
        r2        = guild.get_role(t2.get("team_role")) if t2 else None
        team_ping = " ".join(r.mention for r in (r1, r2) if r)

        scrim_ch_id = next(
            (cid for cid, d in scrim_channels.items()
             if (d["t1_key"] == t1_key and d["t2_key"] == t2_key) or
                (d["t1_key"] == t2_key and d["t2_key"] == t1_key)), None)
        scrim_ch  = guild.get_channel(scrim_ch_id) if scrim_ch_id else None

        # ── Stage 1: team ping, TEAM_PING_MINUTES before ──────────────────────
        team_key = f"{scrim_id}|team_ping"
        if timedelta(minutes=0) < delta <= timedelta(minutes=TEAM_PING_MINUTES) and team_key not in reminded_scrims:
            reminded_scrims.add(team_key)
            if scrim_ch:
                try:
                    content = (
                        (team_ping + "\n") if team_ping else ""
                    ) + (
                        f"# ⏰ Scrim Reminder!\n"
                        f"> **{scrim['team1']}** vs **{scrim['team2']}**\n"
                        f"> Time: **{scrim['time']}** | Date: **{scrim['date']}**\n\n"
                        f"Starting in **less than {TEAM_PING_MINUTES} minutes**!"
                    )
                    await scrim_ch.send(content)
                except Exception:
                    pass

        # ── Stage 2: referee/caster code DM or open-call, OFFICIAL_DM_MINUTES before ──
        dm_key = f"{scrim_id}|official_dm"
        if timedelta(minutes=0) < delta <= timedelta(minutes=OFFICIAL_DM_MINUTES) and dm_key not in official_dm_scrims:
            official_dm_scrims.add(dm_key)
            scrim_key     = make_scrim_key(scrim["team1"], scrim["team2"])
            officials_msg = await get_scrim_message(guild, scrim_key)
            desc          = officials_msg.content if officials_msg else ""
            ref_id  = extract_role_mention(desc, "Referee:")
            cast_id = extract_role_mention(desc, "Caster:")

            code_dm_content = (
                f"# 🔑 Scrim Code\n"
                f">>> **{scrim['team1']}** vs **{scrim['team2']}**\n"
                f"**Match Code:** `{league_code}`\n"
                f"**Time:** {scrim['time']} | **Date:** {scrim['date']}\n\n"
                f"You're assigned to this scrim, starting in **less than {OFFICIAL_DM_MINUTES} minutes!**"
            )

            for uid in filter(None, {ref_id, cast_id}):
                member = guild.get_member(uid)
                if member:
                    try:
                        await member.send(code_dm_content)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            # Open-call for any missing referee/caster
            missing = []
            if ref_id is None:
                missing.append(("Referee:", "Referee", Referee_role))
            if cast_id is None:
                missing.append(("Caster:", "Caster", Caster_role))

            for label, role_name, role_id in missing:
                role = guild.get_role(role_id)
                if not role:
                    continue
                open_content = (
                    f"# 🙋 Official Needed!\n"
                    f"> **{scrim['team1']}** vs **{scrim['team2']}**\n"
                    f"> **Time:** {scrim['time']} | **Date:** {scrim['date']}\n\n"
                    f"> This scrim still needs a **{role_name}** and starts in "
                    f"> **less than {OFFICIAL_DM_MINUTES} minutes**!\n"
                    f"Tap below if you'd like to volunteer."
                )
                view = OpenCallView(scrim_key, label, role_name)
                for member in role.members:
                    try:
                        await member.send(open_content, view=view)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

        # ── Stage 3: post the match code to the channel at start time ────────
        code_key = f"{scrim_id}|code_sent"
        if timedelta(minutes=-1) <= delta <= timedelta(minutes=0) and code_key not in code_sent_scrims:
            code_sent_scrims.add(code_key)
            if scrim_ch:
                try:
                    code_content = (
                        (team_ping + "\n") if team_ping else ""
                    ) + (
                        f"# 🔑 Scrim is now!\n"
                        f"> **{scrim['team1']}** vs **{scrim['team2']}**\n"
                        f"> **Match Code:** `{league_code}`\n\n"
                        f"Good luck, have fun!"
                    )
                    await scrim_ch.send(code_content)
                except Exception:
                    pass

# ── Autocomplete ──────────────────────────────────────────────────────────────
async def category_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=c.name, value=c.name)
            for c in interaction.guild.categories if current.lower() in c.name.lower()][:25]

async def team_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=n.title(), value=n)
            for n in teams if current.lower() in n.lower()][:25]

async def seeding_team_autocomplete(interaction: discord.Interaction, current: str):
    try:
        order  = seeding.get("order", [])
        points = seeding.get("points", {})
        return [app_commands.Choice(name=f"{n.title()}: {points.get(n, 0)} pts", value=n)
                for n in order if current.lower() in n.lower()][:25]
    except Exception:
        return []

async def scrim_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(
                name=f"{s['team1']} vs {s['team2']} | {s['date']} at {s['time']}",
                value=f"{s['team1'].lower()}|{s['team2'].lower()}|{s['time']}|{s['date']}")
            for s in scrims_schedule
            if current.lower() in f"{s['team1']} {s['team2']}".lower()][:25]

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_player_team(player_id: int) -> str | None:
    for name, team in teams.items():
        if player_id in team["players"]:
            return name
    return None

def make_scrim_key(team1: str, team2: str) -> str:
    return f"{team1.lower()}:vs:{team2.lower()}"

async def log_transaction(interaction: discord.Interaction, message: str):
    ch = interaction.guild.get_channel(Transaction_channel)
    if ch:
        await ch.send(message)

async def get_scrim_message(guild: discord.Guild, key: str):
    if key in scrim_messages:
        return scrim_messages[key]
    data = scrim_message_ids.get(key)
    if not data:
        return None
    try:
        ch = guild.get_channel(data["channel_id"])
        if ch is None:
            return None
        msg = await ch.fetch_message(data["message_id"])
        scrim_messages[key] = msg
        return msg
    except (discord.NotFound, discord.Forbidden):
        return None

async def get_mirror_message(guild: discord.Guild, key: str):
    data = scrim_message_ids.get(key)
    if not data or not data.get("mirror_message_id"):
        return None
    try:
        ch = guild.get_channel(Scrims_channel)
        if ch is None:
            return None
        return await ch.fetch_message(data["mirror_message_id"])
    except (discord.NotFound, discord.Forbidden):
        return None

async def get_seeding_message(guild: discord.Guild):
    channel_id = seeding.get("channel_id")
    message_id = seeding.get("message_id")
    if not channel_id or not message_id:
        return None
    try:
        ch = guild.get_channel(channel_id)
        return await ch.fetch_message(message_id) if ch else None
    except (discord.NotFound, discord.Forbidden):
        return None

def extract_role_mention(description: str, label: str) -> Optional[int]:
    """Pull the user id assigned to a role label (e.g. 'Referee:') from scrim message content.
    Officials-message lines are prefixed with '> ', so that prefix is stripped before matching."""
    for line in description.splitlines():
        stripped = line.lstrip("> ").strip()
        if stripped.startswith(label):
            if "None" in stripped:
                return None
            m = MENTION_RE.search(stripped)
            return int(m.group(1)) if m else None
    return None

async def claim_official_role(guild: discord.Guild, key: str, label: str, member: discord.Member) -> bool:
    """Claim an unfilled official role (used by the open-call DM volunteer button).
    Content lines look like '> Referee: **None**', so the target/replacement must match that exact format."""
    msg = await get_scrim_message(guild, key)
    if not msg:
        return False
    content = msg.content
    target = f"{label} **None**"
    if target not in content:
        return False  # already taken by someone else
    content = content.replace(target, f"{label} **{member.mention}**")
    try:
        await msg.edit(content=content)
    except Exception:
        return False

    mirror = await get_mirror_message(guild, key)
    if mirror:
        try:
            if target in mirror.content:
                mirror_content = mirror.content.replace(target, f"{label} **{member.mention}**")
                await mirror.edit(content=mirror_content)
        except Exception:
            pass
    return True

def build_seeding_content(order, points, ended=False, qualifiers=None):
    if not ended:
        desc = "# SCL Season's Seeding 🎯\n**Current seedings based on team scores.**"
    else:
        desc = f"# SCL Seeding Results 🏆\n**Top {qualifiers} teams have moved on! Congratulations!**"
    lines = []
    for rank, name in enumerate(order, 1):
        d   = teams.get(name, {})
        pts = points.get(name, 0)
        pfx = ("✅" if rank <= qualifiers else "❌") if (ended and qualifiers) else ""
        lines.append(f"> {pfx} **{rank}. {name.title()}**\n"
                     f"> **{d.get('wins',0)}W | {d.get('losses',0)}L | {d.get('draws',0)}D | {pts}pts**")
    return desc + "\n\n" + "\n\n".join(lines)

async def apply_seeding_result(interaction, winner, loser, label):
    if not (seeding and seeding.get("order") and not seeding.get("locked")):
        return
    win_pts  = seeding.get("win_points", 0)
    loss_pts = seeding.get("loss_points", 0)
    points   = seeding.get("points", {})
    updated  = False
    if winner in points:
        points[winner] = points.get(winner, 0) + win_pts
        updated = True
    if loser in points:
        points[loser] = points.get(loser, 0) + loss_pts
        updated = True
    if updated:
        order            = sorted(points, key=lambda k: points[k], reverse=True)
        seeding["order"] = order
        seeding["points"] = points
        save_seeding(seeding)
        msg = await get_seeding_message(interaction.guild)
        if msg:
            await msg.edit(content=build_seeding_content(order, points=points))

def record_team_join(player_id, team_name):
    h = str(player_id)
    player_history.setdefault(h, []).append(
        {"team": team_name, "action": "joined", "timestamp": discord.utils.utcnow().isoformat()})
    save_player_history(player_history)

def record_team_leave(player_id, team_name):
    h = str(player_id)
    player_history.setdefault(h, []).append(
        {"team": team_name, "action": "left", "timestamp": discord.utils.utcnow().isoformat()})
    save_player_history(player_history)

def role_pings(guild: discord.Guild) -> str:
    roles = [guild.get_role(r) for r in (Commentator_role, Caster_role, Referee_role)]
    return " ".join(r.mention for r in roles if r)

# ── Confirmation View ─────────────────────────────────────────────────────────
class ConfirmView(discord.ui.View):
    """Generic yes/no confirmation. callback(interaction) is called on confirm."""
    def __init__(self, callback, label: str = "Confirm", danger: bool = True):
        super().__init__(timeout=30)
        self._callback = callback
        confirm_btn = discord.ui.Button(
            label=label,
            style=discord.ButtonStyle.secondary,
            emoji="⚠️" if danger else "✅")
        confirm_btn.callback = self._confirm
        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
        cancel_btn.callback = self._cancel
        self.add_item(confirm_btn)
        self.add_item(cancel_btn)

    async def _confirm(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await self._callback(interaction)

    async def _cancel(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Cancelled.", view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Open-call view (DM'd to refs/casters when a scrim is missing one) ────────
class OpenCallView(discord.ui.View):
    def __init__(self, key: str, label: str, role_name: str):
        super().__init__(timeout=1800) 
        self.key       = key
        self.label     = label      
        self.role_name = role_name  

    @discord.ui.button(label="Volunteer", style=discord.ButtonStyle.secondary, emoji="🙋")
    async def volunteer(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = had3sbot.get_guild(Server_id.id)
        if not guild:
            await interaction.response.send_message("Server unavailable right now.", ephemeral=True); return
        member = guild.get_member(interaction.user.id)
        if not member:
            await interaction.response.send_message("Couldn't find you in the server.", ephemeral=True); return

        claimed = await claim_official_role(guild, self.key, self.label, member)
        for item in self.children:
            item.disabled = True
        if claimed:
            await interaction.response.edit_message(
                content=f"✅ You're now the **{self.role_name}** for this scrim. Thanks for volunteering!",
                view=self)
        else:
            await interaction.response.edit_message(
                content=f"Someone already claimed the **{self.role_name}** spot for this scrim.",
                view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── ScrimThingy ───────────────────────────────────────────────────────────────
class ScrimThingy(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # persistent

    async def has_role(self, interaction: discord.Interaction, *role_ids: int) -> bool:
        if not any(r.id in role_ids for r in interaction.user.roles):
            await interaction.response.send_message(
                "You don't have the required role for this.", ephemeral=True)
            return False
        return True

    def lock_if_full(self, content: str):
        all_filled = (
            "Commentator: **None**"     not in content and
            "2nd Commentator: **None**" not in content and
            "Referee: **None**"         not in content and
            "Caster: **None**"          not in content)
        if all_filled:
            for item in self.children:
                if hasattr(item, "custom_id") and item.custom_id != "scrim:leave":
                    item.disabled = True

    async def sync_mirror(self, interaction: discord.Interaction, content: str):
        key = next(
            (k for k, v in scrim_message_ids.items()
             if v.get("channel_id") == interaction.channel.id
             and v.get("message_id") == interaction.message.id), None)
        if key is None:
            return
        mirror = await get_mirror_message(interaction.guild, key)
        if not mirror:
            return
        try:
            lines = content.splitlines()
            # Strip both "# " and the "⚔️" emoji before splitting the team names.
            header = lines[0].split("⚔️", 1)[-1].strip()
            team1, team2 = [t.strip() for t in header.split(" vs ")]
            # Strip the "> " blockquote prefix before parsing the time/date line.
            time_date = lines[1].lstrip("> ").strip().split(" ", 1)
            time = time_date[0]
            date = time_date[1] if len(time_date) > 1 else ""
            mirror_content = build_scrim_content(time, date, team1, team2)
            role_line_re = re.compile(
                r"^>\s*(Commentator|2nd Commentator|Referee|Caster):\s*\*\*(.+?)\*\*$")
            for line in lines[2:]:
                m = role_line_re.match(line.strip())
                if m:
                    role, value = m.group(1), m.group(2)
                    mirror_content = mirror_content.replace(
                        f"> {role}: **None**", f"> {role}: **{value}**")
            await mirror.edit(content=mirror_content)
        except Exception:
            pass

    @discord.ui.button(label="Claim Commentator",     style=discord.ButtonStyle.secondary, emoji="🎙️", custom_id="scrim:commentator")
    async def com(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.has_role(interaction, Commentator_role): return
        content = interaction.message.content
        if interaction.user.mention in content:
            await interaction.response.send_message("You already claimed a role.", ephemeral=True); return
        if "> Commentator: **None**" not in content:
            await interaction.response.send_message("Commentator already taken.", ephemeral=True); return
        content = content.replace("> Commentator: **None**", f"> Commentator: **{interaction.user.mention}**")
        button.disabled   = True
        self.lock_if_full(content)
        await interaction.response.edit_message(content=content, view=self)
        await self.sync_mirror(interaction, content)

    @discord.ui.button(label="Claim 2nd Commentator", style=discord.ButtonStyle.secondary, emoji="🎤", custom_id="scrim:commentator2")
    async def com2(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.has_role(interaction, Commentator_role): return
        content = interaction.message.content
        if interaction.user.mention in content:
            await interaction.response.send_message("You already claimed a role.", ephemeral=True); return
        if "> 2nd Commentator: **None**" not in content:
            await interaction.response.send_message("2nd Commentator already taken.", ephemeral=True); return
        content = content.replace("> 2nd Commentator: **None**", f"> 2nd Commentator: **{interaction.user.mention}**")
        button.disabled   = True
        self.lock_if_full(content)
        await interaction.response.edit_message(content=content, view=self)
        await self.sync_mirror(interaction, content)

    @discord.ui.button(label="Claim Referee",         style=discord.ButtonStyle.secondary, emoji="⁉️", custom_id="scrim:referee")
    async def ref(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.has_role(interaction, Referee_role): return
        content = interaction.message.content
        if interaction.user.mention in content:
            await interaction.response.send_message("You already claimed a role.", ephemeral=True); return
        if "> Referee: **None**" not in content:
            await interaction.response.send_message("Referee already taken.", ephemeral=True); return
        content = content.replace("> Referee: **None**", f"> Referee: **{interaction.user.mention}**")
        button.disabled   = True
        self.lock_if_full(content)
        await interaction.response.edit_message(content=content, view=self)
        await self.sync_mirror(interaction, content)

    @discord.ui.button(label="Claim Caster",          style=discord.ButtonStyle.secondary, emoji="📸", custom_id="scrim:caster")
    async def cast(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.has_role(interaction, Caster_role): return
        content = interaction.message.content
        if interaction.user.mention in content:
            await interaction.response.send_message("You already claimed a role.", ephemeral=True); return
        if "> Caster: **None**" not in content:
            await interaction.response.send_message("Caster already taken.", ephemeral=True); return
        content = content.replace("> Caster: **None**", f"> Caster: **{interaction.user.mention}**")
        button.disabled   = True
        self.lock_if_full(content)
        await interaction.response.edit_message(content=content, view=self)
        await self.sync_mirror(interaction, content)

    @discord.ui.button(label="Exit Role", style=discord.ButtonStyle.secondary, emoji="🚫", custom_id="scrim:leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.has_role(interaction, Caster_role, Commentator_role, Referee_role): return
        await interaction.response.defer()
        content = interaction.message.content
        if interaction.user.mention not in content:
            await interaction.followup.send("You don't have a role in this scrim.", ephemeral=True); return
        role_labels = {
            "scrim:commentator":  "Commentator:",
            "scrim:commentator2": "2nd Commentator:",
            "scrim:referee":      "Referee:",
            "scrim:caster":       "Caster:",
        }
        for item in self.children:
            if hasattr(item, "custom_id") and item.custom_id in role_labels:
                label      = role_labels[item.custom_id]
                full_entry = f"> {label} **{interaction.user.mention}**"
                if full_entry in content:
                    content       = content.replace(full_entry, f"> {label} **None**")
                    item.disabled = False
        await interaction.message.edit(content=content, view=self)
        await self.sync_mirror(interaction, content)

    @discord.ui.button(label="Cancel Scrim", style=discord.ButtonStyle.secondary, emoji="❌", custom_id="scrim:cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to cancel scrims.", ephemeral=True); return

        async def do_cancel(confirm_interaction: discord.Interaction):
            content = "# ❌ Scrim Cancelled\n" + "\n".join(interaction.message.content.split("\n")[1:])
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(content=content, view=self)
            await self.sync_mirror(interaction, content)

            key = next((k for k, v in scrim_message_ids.items()
                        if v.get("message_id") == interaction.message.id), None)
            if key:
                parts = key.split(":vs:", 1)
                if len(parts) == 2:
                    t1, t2 = parts
                    new_schedule = [g for g in scrims_schedule
                                    if not (g["team1"].lower() == t1 and g["team2"].lower() == t2)]
                    scrims_schedule.clear()
                    scrims_schedule.extend(new_schedule)
                    save_scrims(scrims_schedule)
                scrim_messages.pop(key, None)
                scrim_message_ids.pop(key, None)
                save_scrim_messages(scrim_message_ids)

        await interaction.response.send_message(
            "Are you sure you want to cancel this scrim?",
            view=ConfirmView(do_cancel, label="Cancel Scrim"), ephemeral=True)


# ── Message builders ──────────────────────────────────────────────────────────
def build_scrim_content(time: str, date: str, team1: str, team2: str) -> str:
    return (
        "# ⚔️ SCL Official Scrim\n"
        "## Scrim Details:\n\n"
        f"> Time: **{time}**\n"
        f"> Day: **{date}**\n"
        f"> First Team: **{team1}**\n"
        f"> Second Team: **{team2}**\n\n"
        "> Commentator: **None**\n"
        "> 2nd Commentator: **None**\n"
        "> Referee: **None**\n"
        "> Caster: **None**"
    )

def build_officials_content(time: str, date: str, team1: str, team2: str) -> str:
    return (
        f"# ⚔️ {team1} vs {team2}\n"
        f"> {time} {date}\n"
        "> Commentator: **None**\n"
        "> 2nd Commentator: **None**\n"
        "> Referee: **None**\n"
        "> Caster: **None**"
    )

async def post_scrim_to_channels(guild, key, time, date, team1, team2):
    officials_ch = guild.get_channel(Officials_channel)
    scrims_ch    = guild.get_channel(Scrims_channel)
    if not officials_ch:
        raise ValueError(f"Officials channel {Officials_channel} not found.")
    if not scrims_ch:
        raise ValueError(f"Scrims channel {Scrims_channel} not found.")

    officials_content = build_officials_content(time, date, team1, team2)
    mirror_content     = build_scrim_content(time, date, team1, team2)

    staff_pings = role_pings(guild)

    officials_msg = await officials_ch.send(
        (staff_pings + "\n" if staff_pings else "") + officials_content, view=ScrimThingy())
    mirror_msg    = await scrims_ch.send(mirror_content)

    scrim_messages[key]    = officials_msg
    scrim_message_ids[key] = {
        "channel_id":        officials_ch.id,
        "message_id":        officials_msg.id,
        "mirror_message_id": mirror_msg.id,
    }
    save_scrim_messages(scrim_message_ids)
    return officials_msg, mirror_msg

async def update_posted_scrim_time(guild, key, new_time, new_date) -> bool:
    """Update the time/date on an already-posted scrim message without wiping claimed roles.
    Returns True if a posted scrim was found and updated, False if nothing exists yet."""
    officials_msg = await get_scrim_message(guild, key)
    mirror_msg    = await get_mirror_message(guild, key)
    if not officials_msg and not mirror_msg:
        return False

    role_labels = ("> Commentator:", "> 2nd Commentator:", "> Referee:", "> Caster:")

    if officials_msg:
        new_lines = []
        for line in officials_msg.content.splitlines():
            if line.startswith("> ") and not line.startswith(role_labels):
                new_lines.append(f"> {new_time} {new_date}")
            else:
                new_lines.append(line)
        try:
            await officials_msg.edit(content="\n".join(new_lines))
        except Exception:
            pass

    if mirror_msg:
        new_lines = []
        for line in mirror_msg.content.splitlines():
            if line.startswith("> Time:"):
                new_lines.append(f"> Time: **{new_time}**")
            elif line.startswith("> Day:"):
                new_lines.append(f"> Day: **{new_date}**")
            else:
                new_lines.append(line)
        try:
            await mirror_msg.edit(content="\n".join(new_lines))
        except Exception:
            pass

    return True

async def update_scrim_channel_emoji(guild: discord.Guild, t1_key: str, t2_key: str, emoji: str):
    """Update the emoji prefix on a scrim channel to reflect its current status."""
    for cid, data in scrim_channels.items():
        if (data["t1_key"] == t1_key and data["t2_key"] == t2_key) or \
           (data["t1_key"] == t2_key and data["t2_key"] == t1_key):
            ch = guild.get_channel(cid)
            if ch:
                try:
                    await ch.edit(name=f"「{emoji}」{t1_key}-vs-{t2_key}")
                except Exception:
                    pass
            break


def update_schedule_entry_time(team1: str, team2: str, new_time: str, new_date: str) -> bool:
    for s in scrims_schedule:
        if s["team1"].lower() == team1.lower() and s["team2"].lower() == team2.lower():
            s["time"]         = new_time
            s["date"]         = new_date
            s["datetime_utc"] = parse_scrim_datetime(new_time, new_date)
            save_scrims(scrims_schedule)
            # Allow fresh reminders to fire if the new time is still far enough away
            scrim_id = f"{s['team1']}|{s['team2']}"
            reminded_scrims.discard(f"{scrim_id}|team_ping")
            official_dm_scrims.discard(f"{scrim_id}|official_dm")
            code_sent_scrims.discard(f"{scrim_id}|code_sent")
            return True
    return False

# ── Views ─────────────────────────────────────────────────────────────────────
class MyInvitesView(discord.ui.View):
    def __init__(self, player: discord.Member, invites: list):
        super().__init__(timeout=60)
        self.player = player
        for inv in invites:
            self.add_item(InviteButton(inv["team_name"], inv["inviter_id"]))


class InviteButton(discord.ui.Button):
    def __init__(self, team_name: str, inviter_id: int):
        super().__init__(label=team_name.title(), style=discord.ButtonStyle.secondary, emoji="📨")
        self.team_name  = team_name
        self.inviter_id = inviter_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.player.id:
            await interaction.response.send_message("These invites are not for you.", ephemeral=True); return
        view = InvitingThing(interaction.user, self.team_name, self.inviter_id, self.view)
        await interaction.response.edit_message(
            content=f"You have an invite from **{self.team_name.title()}**. Would you like to `Accept` or `Decline`?",
            view=view)


class ScrimProposalView(discord.ui.View):
    def __init__(self, t1_key, t2_key, time, date, proposer_id, other_captain_id, proposal_key: str = ""):
        super().__init__(timeout=None)  # persistent
        self.t1_key           = t1_key
        self.t2_key           = t2_key
        self.time             = time
        self.date             = date
        self.proposer_id      = proposer_id
        self.other_captain_id = other_captain_id
        self.proposal_key     = proposal_key

        accept_btn = discord.ui.Button(
            label="Accept", style=discord.ButtonStyle.secondary, emoji="✅",
            custom_id=f"proposal_accept:{proposal_key}")
        accept_btn.callback = self.accept
        decline_btn = discord.ui.Button(
            label="Decline", style=discord.ButtonStyle.secondary, emoji="❌",
            custom_id=f"proposal_decline:{proposal_key}")
        decline_btn.callback = self.decline
        self.add_item(accept_btn)
        self.add_item(decline_btn)

    def is_other_captain(self, interaction: discord.Interaction) -> bool:
        uid   = interaction.user.id
        team1 = teams.get(self.t1_key, {})
        team2 = teams.get(self.t2_key, {})
        on1   = self.proposer_id in (team1.get("captain"), team1.get("co_captain"))
        return uid in (team2.get("captain"), team2.get("co_captain")) if on1 \
               else uid in (team1.get("captain"), team1.get("co_captain"))

    def _cleanup_proposal(self):
        if self.proposal_key and self.proposal_key in pending_proposals:
            del pending_proposals[self.proposal_key]
            save_proposals(pending_proposals)

    async def accept(self, interaction: discord.Interaction):
        if not self.is_other_captain(interaction):
            await interaction.response.send_message("Only the other captain can respond.", ephemeral=True); return
        for item in self.children:
            item.disabled = True
        await interaction.response.send_message(f"<@{self.proposer_id}> <@{self.other_captain_id}>\n # ✅ Scrim confirmed\n> **{self.date}** at **{self.time}**!\n")
        await interaction.message.edit(view=self)
        self._cleanup_proposal()
        key = make_scrim_key(self.t1_key, self.t2_key)
        updated = await update_posted_scrim_time(interaction.guild, key, self.time, self.date)
        if updated:
            update_schedule_entry_time(self.t1_key.title(), self.t2_key.title(), self.time, self.date)
        else:
            await post_scrim_to_channels(
                interaction.guild, key, self.time, self.date,
                self.t1_key.title(), self.t2_key.title())
            scrims_schedule.append({
                "time": self.time, "date": self.date,
                "team1": self.t1_key.title(), "team2": self.t2_key.title(),
                "datetime_utc": parse_scrim_datetime(self.time, self.date),
                "league_code": f"SCL{random.randint(100, 999)}"})
            save_scrims(scrims_schedule)
        await update_scrim_channel_emoji(interaction.guild, self.t1_key, self.t2_key, "⏳")

    async def decline(self, interaction: discord.Interaction):
        if not self.is_other_captain(interaction):
            await interaction.response.send_message("Only the other captain can respond.", ephemeral=True); return
        for item in self.children:
            item.disabled = True
        await interaction.response.send_message(
            f"❌ Proposal declined. <@{self.proposer_id}>, suggest a new time with `/suggest_time`.")
        await interaction.message.edit(view=self)
        self._cleanup_proposal()


class InvitingThing(discord.ui.View):
    def __init__(self, player, team_name, inviter_id, previous_view):
        super().__init__(timeout=60)
        self.player        = player
        self.team_name     = team_name
        self.inviter_id    = inviter_id
        self.previous_view = previous_view

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.secondary, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        lower = self.team_name.lower()
        if lower not in teams:
            await interaction.response.edit_message(content="This team no longer exists.", view=None); return
        if is_staff_member(self.player):
            await interaction.response.edit_message(
                content="You have the staff role and can't join a team.", view=None); return
        # Use a lock to prevent race conditions with simultaneous accepts
        async with teams_lock:
            team = teams[lower]
            if team.get("locked"):
                await interaction.response.edit_message(content="Roster is locked.", view=None); return
            if self.player.id in team["players"]:
                await interaction.response.edit_message(content="Already on this team.", view=None); return
            existing = get_player_team(self.player.id)
            if existing and existing != lower:
                await interaction.response.edit_message(
                    content=f"You're on **{existing.title()}**, please leave first.", view=None); return
            if len(team["players"]) >= 12:
                await interaction.response.edit_message(content="Team is full.", view=None); return
            role = interaction.guild.get_role(team["team_role"])
            if role is None:
                await interaction.response.edit_message(content="Team role not found.", view=None); return
            tpr = get_tpr(interaction.guild)
            roles_to_add = [role] + ([tpr] if tpr else [])
            await self.player.add_roles(*roles_to_add)
            team["players"].append(self.player.id)
            record_team_join(self.player.id, lower)
            if self.player.id in pending_invites:
                pending_invites[self.player.id] = [
                    i for i in pending_invites[self.player.id] if i["team_name"] != self.team_name]
                save_invites(pending_invites)
            save_teams(teams)
        await log_transaction(interaction, f"{self.player.mention} joined **{self.team_name.title()}**.")
        await interaction.response.edit_message(content=f"You've joined **{self.team_name.title()}**!", view=None)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.secondary, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("Not for you.", ephemeral=True); return
        if self.player.id in pending_invites:
            pending_invites[self.player.id] = [
                i for i in pending_invites[self.player.id] if i["team_name"] != self.team_name]
            save_invites(pending_invites)
        await interaction.response.edit_message(
            content=f"You declined the invite to **{self.team_name.title()}**.", view=None)



@had3sbot.event
async def on_member_remove(member: discord.Member):
    team_name = get_player_team(member.id)
    if not team_name:
        return
    team = teams[team_name]
    was_captain    = team["captain"]    == member.id
    was_co_captain = team["co_captain"] == member.id
    team["players"].remove(member.id)
    record_team_leave(member.id, team_name)
    if was_captain:    team["captain"]    = None
    if was_co_captain: team["co_captain"] = None
    save_teams(teams)
    still_on_team = get_player_team(member.id)
    tpr = member.guild.get_role(team_player_role)
    if tpr and still_on_team is None:
        try:
            await member.remove_roles(tpr)
        except Exception:
            pass
    if was_captain:
        await revoke_general_captain_if_unneeded(member.guild, member.id)
    if was_co_captain:
        await revoke_general_cocaptain_if_unneeded(member.guild, member.id)
    ch = member.guild.get_channel(Transaction_channel)
    if ch:
        await ch.send(f"{member.mention} (`{member.name}`) left and was removed from **{team_name.title()}**.")


# ── Commands ──────────────────────────────────────────────────────────────────
@had3sbot.tree.command(name="print", description="Print a message", guild=Server_id)
@is_premium()
async def msg(interaction: discord.Interaction, message: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    await interaction.response.send_message("Sent!", ephemeral=True)
    await interaction.channel.send(message)


@had3sbot.tree.command(name="dm_user", description="Send a DM to a user.", guild=Server_id)
@is_premium()
@app_commands.describe(user="User to DM", message="Message to send")
async def dm_user(interaction: discord.Interaction, user: discord.Member, message: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if user.bot:
        await interaction.response.send_message("Can't DM a bot.", ephemeral=True); return
    try:
        await user.send(message)
        await interaction.response.send_message(f"DM sent to {user.mention}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(f"Couldn't DM {user.mention}.", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.response.send_message(f"Failed: {e}", ephemeral=True)


class ScrimEmojiContainer(discord.ui.LayoutView):
    container = discord.ui.Container(
        discord.ui.TextDisplay(
            "# 🏓 Scrim Channel Emoji Guide\n"
            "Each private scrim channel's name prefix shows its current status:\n\n"
            "> **「⚔️」**: Default channel emoji, no time has been set yet. Waiting on `/suggest_time` or `/set_time`.\n"
            "> **「⏳」**: A time has been set and the scrim is scheduled, awaiting the match.\n"
            "> **「✅」**: The scrim has been completed and the score recorded via `/end_scrim`.\n"
            "> **「☑️」**: The scrim ended in a forfeit or auto-forfeit.\n"
        )
    )

@had3sbot.tree.command(name="scrim_emoji_guide", description="Explains the scrim channel emoji statuses", guild=Server_id)
async def scrim_emoji_guide(interaction: discord.Interaction):
    await interaction.response.send_message("Emoji guide sent.", ephemeral=True)
    await interaction.channel.send(view = ScrimEmojiContainer())

# ── /info (Components V2  no side accent bar) ──────────────────────────────
class InfoLayout(discord.ui.LayoutView):
    container = discord.ui.Container(
        discord.ui.TextDisplay(
            "# 🤖 SCL Command Guide\n"
            "What every command does and who can use it:\n\n"
            "## 👤 Anyone\n"
            "> **/info**: Shows this guide.\n"
            "> **/roster**: Shows a team's roster.\n"
            "> **/check_invites**: View and respond to your pending team invites.\n"
            "> **/leave_team**: Leave your current team.\n"
            "> **/command_guide**: Shows a detailed guide for all commands and how to use them.\n"
            "## 👑 Captains & Co-Captains\n"
            "> **/kick_player**: Removes a player from your team.\n"
            "> **/assign_cocaptain**: Assigns a co-captain to your team.\n"
            "> **/transfer_captain**: Transfers captaincy to another player on the team.\n"
            "> **/invite_player**: Invites a player to join your team.\n"
            "> **/cancel_invite**: Cancels a pending invite you sent.\n"
            "## 🔧 Administrators\n"
            "> **/create_team**: Creates a new team with captain, co-captain, and roles.\n"
            "> **/disband_team**: Disbands a team and deletes its roles.\n"
            "> **/lock_rosters**: Locks all team rosters preventing changes.\n"
            "> **/unlock_rosters**: Unlocks all team rosters allowing changes.\n"
            "> **/assign_captain**: Assigns a captain to a team.\n"
            "## 💎 Premium\n"
            "> **/print**: Prints a message to the channel.\n"
            "> **/dm_user**: Sends a direct message to a user.\n"
            "> **/disband_all**: Disbands every team at once.\n"
            "> **/list_teams**: Lists all active teams.\n"
            "> **/rename_team**: Renames an existing team and updates its roles.\n"
            "> **/add_player**: Manually adds a player to a team.\n"
            "> **/player_info**: Shows a player's current team, role, record, and team history.\n"
            "> **/set_scrim**: Creates an official scrim embed.\n"
            "> **/reschedule_scrim**: Changes the time/date of an existing scrim.\n"
            "> **/set_time**: Forcibly sets a scrim time in a scrim channel, no approval needed.\n"
            "> **/end_scrim**: Records the final score of a scrim and removes team access from the scrim channel.\n"
            "> **/check_scrims**: Quick list of all upcoming scrims.\n"
            "> **/create_scrim_channel**: Creates a private channel for two teams to coordinate their scrim.\n"
            "> **/suggest_time**: Proposes a scrim time for the other captain to accept or decline.\n"
            "> **/forfeit_scrim**: Marks any team as forfeiting a scrim.\n"
            "> **/autoforfeit_scrim**: Flags or immediately triggers an auto-forfeit for a team.\n"
            "> **/create_seeding**: Starts a seeding round and tracks team scores.\n"
            "> **/edit_seeding**: Manually adds or removes wins/points from a team in seeding.\n"
            "> **/end_seeding**: Ends the seeding round and displays which teams advanced.\n\n"
            "SCL Season Management System - Created by Had3s"
        )
    )

@had3sbot.tree.command(name="info", description="Bot command guide", guild=Server_id)
async def info(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True); return
    await interaction.response.send_message("Info pannel sent", ephemeral = True)
    await interaction.channel.send(view=InfoLayout())   



Free_commands = {
    "🚀 Getting Started": [
        "## How this bot works\n"
        "SCL organizes your server around **teams**, **scrims** (practice matches), and **seeding** (a scoring round to decide who advances).\n\n"
        "**If you're a player:** join a team via invite (`/check_invites`) or ask a captain to send you one (`/invite_player`). "
        "Once you're on a team you'll automatically get pinged for scrims and see your record with `/player_info`.\n\n"
        "**If you're a captain:** you run your team's invites and roster. Use `/invite_player` to recruit, "
        "`/kick_player` to remove someone, and `/suggest_time` inside your scrim channel to lock in a match time with the other captain.\n\n"
        "**If you're an admin:** you set up teams (`/create_team`), open scrim channels (`/create_scrim_channel`), "
        "and record results (`/end_scrim`). Use `/command_guide` any time you need this menu again."
    ],
    "👤 For Players": [
        "## Joining and managing your spot\n"
        "**Getting on a team:** A captain either sends you an invite (check it with `/check_invites`, accept or decline right there), "
        "or an admin adds you directly with `/add_player`. You can only be on one team at a time.\n\n"
        "**Checking things:** `/roster <team>` shows any team's full lineup. `/player_info <player>` shows someone's current team, "
        "role, W/L/D record, and their full join/leave history.\n\n"
        "**Leaving:** `/leave_team` removes you from your current team immediately, no approval needed, unless rosters are locked "
        "by an admin for the season.\n\n"
        "*Note: staff members can't be added to a competing team.*"
    ],
    "👑 For Captains & Co-Captains": [
        "## Running your roster\n"
        "**Recruiting:** `/invite_player` sends an invite the player accepts/declines themselves. Sent one by mistake? `/cancel_invite` pulls it back "
        "before they respond.\n\n"
        "**Removing someone:** `/kick_player`: co-captains can kick regular players but not the captain.\n\n"
        "**Delegating:** `/assign_cocaptain` gives someone else invite/kick powers on your team. `/transfer_captain` hands over full captaincy "
        "(useful if you're stepping away).\n\n"
        "## Scheduling a scrim\n"
        "Once an admin creates a private scrim channel for your matchup, run **`/suggest_time`** *inside that channel* with your proposed time and date. "
        "The other captain gets a button to Accept or Decline. If they accept, the scrim is automatically posted and scheduled, no admin needed. "
        "If declined, just suggest again with a new time.\n\n"
        "**Can't make it?** `/forfeit_scrim` inside your scrim channel logs a forfeit and the result immediately, only usable on your own team unless you're an admin."
    ],
    "🔧 For Admins: Teams": [
        "## Setting up the league\n"
        "**`/create_team`**: creates a team, assigns captain/co-captain, and generates a dedicated Discord role for them automatically.\n\n"
        "**`/assign_captain`**: reassign captaincy at any point (separate from a captain choosing to `/transfer_captain` themselves).\n\n"
        "**`/lock_rosters` / `/unlock_rosters`**: freeze all rosters league-wide (e.g. right before a tournament cutoff) so no invites/kicks/leaves "
        "can happen until you unlock them.\n\n"
        "**`/disband_team`**: permanently removes a team and its role. This can't be undone, so you'll get a confirmation prompt first."
    ],
}

Premium_commands = {
    "🏁 Scrims: The Full Workflow": [
        "## How a scrim goes from start to finish\n"
        "**1. Set it up.** Either:\n"
        "  • `/create_scrim_channel`: makes a private channel just for the two teams to coordinate. Nothing is posted or pinged yet"
        "the captains then use `/suggest_time` in there to agree on a slot, **or**\n"
        "  • `/set_scrim`: you set the time/date yourself and it's posted immediately, no captain negotiation needed.\n\n"
        "**2. Reminders fire automatically**: no command needed:\n"
        "  • 20 minutes before: both teams' roles get pinged in the scrim/scrims channel.\n"
        "  • 15 minutes before: the assigned Referee and Caster get DM'd the match code privately. If either role is unfilled, "
        "everyone with that role gets an open call DM with a **Volunteer** button.\n"
        "  • At start time: the match code is posted publicly in the channel.\n\n"
        "**3. Need to change the time after it's posted?** `/reschedule_scrim` (works anywhere) or `/set_time` (used inside the scrim channel, "
        "skips captain approval, good for last-minute admin overrides).\n\n"
        "**4. Something goes wrong?** `/forfeit_scrim` (a captain forfeits their own team) or `/autoforfeit_scrim` (admin-only, for no-shows) "
        "logs the result and posts it to the channel immediately, this works even if a time was never set for the scrim.\n\n"
        "**5. Wrap it up.** `/end_scrim` records the final score, updates both teams' W/L/D and seeding points if a seeding round is active, "
        "posts the result to the scores channel, and offers to delete the now-unneeded scrim channel.\n\n"
        "**Anytime:** `/check_scrims`: quick list of everything still upcoming."
    ],
    "🌱 Seeding": [
        "## Running a seeding round\n"
        "**`/create_seeding win_points loss_points`** starts a round, every team starts at 0 points, and resets W/L/D counters. "
        "From then on, every `/end_scrim` result automatically adds points and re-sorts the leaderboard for you.\n\n"
        "**`/edit_seeding`** manually nudges a team's wins/points up or down, handy for correcting a mistake or handling a special ruling.\n\n"
        "**`/end_seeding qualifiers`** locks the round and marks the top N teams as having advanced, no more automatic point changes after this."
    ],
    "💎 Admin Utilities": [
        "## Extra tools for running the server\n"
        "**`/list_teams`** / **`/team_stats`**, quick overviews: who exists, and who's winning.\n\n"
        "**`/add_player`**, skip the invite flow and place someone on a team directly.\n\n"
        "**`/rename_team`**, renames a team and keeps its role, scrims, and seeding entry in sync.\n\n"
        "**`/disband_all`**, wipes every team at once (season reset). Confirmation required, this can't be undone.\n\n"
        "**`/print`** / **`/dm_user`**, send a message through the bot to a channel or a user's DMs.\n\n"
        "**`/send_files`**, grabs a backup of all your JSON data files (teams, scrims, seeding, etc.) as attachments."
    ],
}


def build_guide_text(category: str) -> str:
    if Premium_enabled:
        total_commands = Free_commands.get(category, []) + Premium_commands.get(category, [])
    else:
        total_commands = Free_commands.get(category, [])
    if not total_commands:
        return "# 🤖 SCL Bot Guide\nCategory not found."
    return "# 🤖 SCL Bot Guide\n" + "\n\n".join(total_commands)


class CommandChoose(Select):
    def __init__(self):
        all_commands = list(Free_commands.keys())
        if Premium_enabled:
            all_commands += [cmd for cmd in Premium_commands if cmd not in all_commands]
        options = [discord.SelectOption(label=command, value=command) for command in all_commands]
        super().__init__(placeholder="Select a command/category", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        new_view = CommandGuideLayout(self.values[0])
        await interaction.response.edit_message(view=new_view)


class CommandGuideLayout(discord.ui.LayoutView):
    def __init__(self, category: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(discord.ui.TextDisplay(build_guide_text(category))))
        row = discord.ui.ActionRow()
        row.add_item(CommandChoose())
        self.add_item(row)


@had3sbot.tree.command(name="command_guide", description="Show the command guide with all SCL bot commands", guild=Server_id)
async def commands_panel(interaction: discord.Interaction):
    da_commands = next(iter(Free_commands))
    view = CommandGuideLayout(da_commands)
    await interaction.response.send_message(view=view, ephemeral=True)


@had3sbot.tree.command(name="create_team", description="Create a new team", guild=Server_id)
async def create_team(interaction: discord.Interaction, team_name: str,
                      captain_name: discord.Member,
                      co_captain_name: Optional[discord.Member] = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if team_name.lower() in teams:
        await interaction.response.send_message(f"**{team_name.title()}** already exists.", ephemeral=True); return
    if teams and any(t.get("locked") for t in teams.values()):
        await interaction.response.send_message("Rosters are currently locked league-wide.", ephemeral=True); return
    for cand, label in [(captain_name, "Captain"), (co_captain_name, "Co-Captain")]:
        if cand and is_staff_member(cand):
            await interaction.response.send_message(
                f"{cand.mention} is a part of staff, they cannot be on a team.", ephemeral=True); return
    for cand, label in [(captain_name, "Captain"), (co_captain_name, "Co-Captain")]:
        if cand:
            ex = get_player_team(cand.id)
            if ex:
                await interaction.response.send_message(
                    f"{cand.mention} is on **{ex.title()}**.", ephemeral=True); return

    await interaction.response.defer(ephemeral=True)
    async with teams_lock:
        tpr             = get_tpr(interaction.guild)
        team_role       = await interaction.guild.create_role(name=team_name.title())
        teams[team_name.lower()] = {
            "name": team_name, "captain": captain_name.id,
            "co_captain": co_captain_name.id if co_captain_name else None,
            "players": [captain_name.id] + ([co_captain_name.id] if co_captain_name else []),
            "wins": 0, "losses": 0, "draws": 0,
            "team_role": team_role.id,
        }
        record_team_join(captain_name.id, team_name.lower())
        if co_captain_name:
            record_team_join(co_captain_name.id, team_name.lower())
        save_teams(teams)
        roles_to_add = [team_role] + ([tpr] if tpr else [])
        await captain_name.add_roles(*roles_to_add)
        if co_captain_name:
            await co_captain_name.add_roles(*roles_to_add)
    await grant_general_captain(interaction.guild, captain_name.id)
    if co_captain_name:
        await grant_general_cocaptain(interaction.guild, co_captain_name.id)
    await log_transaction(interaction,
        f"# **{team_name.title()}** joined SCL\n"
        f"> ### Captain: {captain_name.mention}\n"
        f"> ### Co-Captain: {co_captain_name.mention if co_captain_name else 'None'}")
    await interaction.followup.send(
        f"# 🪸 {team_name} was created.\n### Roles created:\n>>> * {team_role.mention}\n",
        ephemeral=True)


@had3sbot.tree.command(name="re-name_team", description="Rename an existing team", guild=Server_id)
@is_premium()
@app_commands.autocomplete(team_name=team_autocomplete)
async def rename_team(interaction: discord.Interaction, team_name: str, new_name: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    lower = team_name.lower()
    if lower not in teams:
        await interaction.response.send_message(f"**{team_name.title()}** doesn't exist.", ephemeral=True); return
    new_lower = new_name.lower().strip()
    if not new_lower or new_lower in teams:
        await interaction.response.send_message("Invalid new name.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    async with teams_lock:
        team = teams[lower]
        for role_id, new_role_name in [
            (team["team_role"], new_name.title()),
        ]:
            role = interaction.guild.get_role(role_id)
            if role:
                await role.edit(name=new_role_name)
        team["name"]     = new_name.title()
        teams[new_lower] = team
        del teams[lower]
        save_teams(teams)

    async with seeding_lock:
        if seeding and seeding.get("order"):
            seeding["order"] = [new_lower if t == lower else t for t in seeding["order"]]
            if lower in seeding.get("points", {}):
                seeding["points"][new_lower] = seeding["points"].pop(lower)
            save_seeding(seeding)
            seed_msg = await get_seeding_message(interaction.guild)
            if seed_msg:
                pts   = seeding.get("points", {})
                order = seeding.get("order", [])
                await seed_msg.edit(content=build_seeding_content(order, points=pts))

    async with scrims_lock:
        old_keys = [k for k in scrim_message_ids if lower in k.split(":vs:")]
        for old_key in old_keys:
            parts = old_key.split(":vs:")
            if len(parts) == 2:
                new_key = make_scrim_key(
                    new_lower if parts[0] == lower else parts[0],
                    new_lower if parts[1] == lower else parts[1])
                scrim_message_ids[new_key] = scrim_message_ids.pop(old_key)
                if old_key in scrim_messages:
                    scrim_messages[new_key] = scrim_messages.pop(old_key)
        save_scrim_messages(scrim_message_ids)
        for scrim in scrims_schedule:
            if scrim["team1"].lower() == lower:
                scrim["team1"] = new_name.title()
            if scrim["team2"].lower() == lower:
                scrim["team2"] = new_name.title()
        save_scrims(scrims_schedule)

    await log_transaction(interaction, f"**{team_name.title()}** renamed to **{new_name.title()}**")
    await interaction.followup.send(f"Renamed to **{new_name.title()}**.", ephemeral=True)


@had3sbot.tree.command(name="disband_team", description="Disbands an existing team", guild=Server_id)
@app_commands.autocomplete(team_name=team_autocomplete)
async def disband_team(interaction: discord.Interaction, team_name: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    lower = team_name.lower()
    if lower not in teams:
        await interaction.response.send_message(f"**{team_name.title()}** doesn't exist.", ephemeral=True); return
    if teams[lower].get("locked"):
        await interaction.response.send_message("Roster is locked.", ephemeral=True); return

    async def do_disband(confirm_interaction: discord.Interaction):
        await confirm_interaction.followup.send("Disbanding...", ephemeral=True)
        async with teams_lock:
            tpr  = get_tpr(interaction.guild)
            team = teams[lower]
            role_objs  = [interaction.guild.get_role(team["team_role"])]
            player_ids = list(team["players"])
            old_captain    = team.get("captain")
            old_co_captain = team.get("co_captain")
            for pid in player_ids:
                m = interaction.guild.get_member(pid)
                record_team_leave(pid, lower)
                if m:
                    roles_to_remove = [r for r in role_objs if r and r in m.roles]
                    other_team = next((n for n, t in teams.items() if n != lower and pid in t["players"]), None)
                    if tpr and tpr in m.roles and other_team is None:
                        roles_to_remove.append(tpr)
                    if roles_to_remove:
                        await m.remove_roles(*roles_to_remove)
            for role in role_objs:
                try:
                    if role:
                        await role.delete()
                except discord.NotFound:
                    pass
            del teams[lower]
            save_teams(teams)
        if old_captain:
            await revoke_general_captain_if_unneeded(interaction.guild, old_captain)
        if old_co_captain:
            await revoke_general_cocaptain_if_unneeded(interaction.guild, old_co_captain)
        await log_transaction(interaction, f"**{team_name.title()}** disbanded by {interaction.user.mention}.")

    await interaction.response.send_message(
        f"Are you sure you want to disband **{team_name.title()}**? This cannot be undone.",
        view=ConfirmView(do_disband, label="Disband Team"), ephemeral=True)


@had3sbot.tree.command(name="disband_all", description="Disbands all teams", guild=Server_id)
@is_premium()
async def disband_all(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if not teams:
        await interaction.response.send_message("No teams exist.", ephemeral=True); return
    if any(t.get("locked") for t in teams.values()):
        await interaction.response.send_message("Rosters are currently locked.", ephemeral=True); return

    async def do_disband_all(confirm_interaction: discord.Interaction):
        old_captains    = []
        old_co_captains = []
        async with teams_lock:
            tpr = get_tpr(interaction.guild)
            for name in list(teams.keys()):
                team  = teams[name]
                roles = [interaction.guild.get_role(team["team_role"])]
                if team.get("captain"):
                    old_captains.append(team["captain"])
                if team.get("co_captain"):
                    old_co_captains.append(team["co_captain"])
                for pid in team["players"]:
                    m = interaction.guild.get_member(pid)
                    if m:
                        roles_to_remove = [r for r in roles if r and r in m.roles]
                        if tpr and tpr in m.roles:
                            roles_to_remove.append(tpr)
                        if roles_to_remove:
                            await m.remove_roles(*roles_to_remove)
                    record_team_leave(pid, name)
                for role in roles:
                    try:
                        if role:
                            await role.delete()
                    except discord.NotFound:
                        pass
            teams.clear()
            save_teams(teams)
        cap_role   = interaction.guild.get_role(captain_role)
        cocap_role = interaction.guild.get_role(co_captain_role)
        for pid in set(old_captains):
            m = interaction.guild.get_member(pid)
            if m and cap_role and cap_role in m.roles:
                try:
                    await m.remove_roles(cap_role)
                except Exception:
                    pass
        for pid in set(old_co_captains):
            m = interaction.guild.get_member(pid)
            if m and cocap_role and cocap_role in m.roles:
                try:
                    await m.remove_roles(cocap_role)
                except Exception:
                    pass
        await log_transaction(interaction, f"All teams disbanded by {interaction.user.mention}.")

    await interaction.response.send_message(
        f"Are you sure you want to disband all ** {len(teams)} teams**? This cannot be undone.",
        view=ConfirmView(do_disband_all, label="Disband All Teams"), ephemeral=True)


@had3sbot.tree.command(name="list_teams", description="List all active teams", guild=Server_id)
@is_premium()
async def list_teams(interaction: discord.Interaction):
    if not teams:
        await interaction.response.send_message("No teams exist.", ephemeral=True); return
    team_list = "\n".join(f"* **{n.title()}**" for n in teams)
    await interaction.response.send_message(f"## 🏆 Current Teams:\n>>> {team_list}", ephemeral=True)


@had3sbot.tree.command(name="roster", description="Show the roster of a team", guild=Server_id)
@app_commands.autocomplete(team_name=team_autocomplete)
async def roster(interaction: discord.Interaction, team_name: str):
    lower = team_name.lower()
    if lower not in teams:
        await interaction.response.send_message(f"**{team_name.title()}** doesn't exist.", ephemeral=True); return
    team = teams[lower]
    cap  = f"<@{team['captain']}>"    if team["captain"]    else "None"
    coc  = f"<@{team['co_captain']}>" if team["co_captain"] else "None"
    pls  = "\n".join(f"<@{p}>" for p in team["players"]) if team["players"] else "None"
    await interaction.response.send_message(
        f"## **{team_name.title()}** Roster:\n\n"
        f">>> **Captain:** {cap}\n**Co-Captain:** {coc}\n**Players:**\n{pls}",
        ephemeral=True)


@had3sbot.tree.command(name="lock_rosters", description="Lock all team rosters", guild=Server_id)
async def lock_rosters(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if not teams:
        await interaction.response.send_message("No teams exist.", ephemeral=True); return
    for n in teams:
        teams[n]["locked"] = True
    save_teams(teams)
    await log_transaction(interaction, f"All rosters locked by {interaction.user.mention}.")
    await interaction.response.send_message("All Rosters Locked.", ephemeral=True)


@had3sbot.tree.command(name="unlock_rosters", description="Unlock all team rosters", guild=Server_id)
async def cmd_unlock_rosters(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if not teams:
        await interaction.response.send_message("No teams exist.", ephemeral=True); return
    for n in teams:
        teams[n]["locked"] = False
    save_teams(teams)
    await log_transaction(interaction, f"All rosters unlocked by {interaction.user.mention}.")
    await interaction.response.send_message("All Rosters Unlocked.", ephemeral=True)


@had3sbot.tree.command(name="add_player", description="Manually add a player to a team", guild=Server_id)
@is_premium()
@app_commands.autocomplete(team_name=team_autocomplete)
async def cmd_add_player(interaction: discord.Interaction, team_name: str, player: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    lower = team_name.lower()
    if lower not in teams:
        await interaction.response.send_message(f"**{team_name.title()}** doesn't exist.", ephemeral=True); return
    if is_staff_member(player):
        await interaction.response.send_message(
            f"{player.mention} has the staff role and can't be placed on a team.", ephemeral=True); return
    team = teams[lower]
    if team.get("locked"):
        await interaction.response.send_message("Roster is locked.", ephemeral=True); return
    if player.id in team["players"]:
        await interaction.response.send_message(f"{player.mention} is already on this team.", ephemeral=True); return
    if len(team["players"]) >= 12:
        await interaction.response.send_message("Team is full.", ephemeral=True); return
    ex = get_player_team(player.id)
    if ex:
        await interaction.response.send_message(f"{player.mention} is on **{ex.title()}**.", ephemeral=True); return
    role = interaction.guild.get_role(team["team_role"])
    tpr  = get_tpr(interaction.guild)
    roles_to_add = ([role] if role else []) + ([tpr] if tpr else [])
    if roles_to_add:
        await player.add_roles(*roles_to_add)
    team["players"].append(player.id)
    record_team_join(player.id, lower)
    save_teams(teams)
    await log_transaction(interaction, f"{player.mention} manually added to **{team_name.title()}**")
    await interaction.response.send_message(f"{player.mention} added to **{team_name.title()}**.", ephemeral=True)


@had3sbot.tree.command(name="kick_player", description="Kick a player from a team", guild=Server_id)
@app_commands.autocomplete(team_name=team_autocomplete)
async def cmd_kick_player(interaction: discord.Interaction, team_name: str, player: discord.Member):
    lower = team_name.lower()
    if lower not in teams:
        await interaction.response.send_message(f"**{team_name.title()}** doesn't exist.", ephemeral=True); return
    team          = teams[lower]
    is_captain    = team["captain"]    == interaction.user.id
    is_co_captain = team["co_captain"] == interaction.user.id
    is_admin      = interaction.user.guild_permissions.administrator
    if team.get("locked"):
        await interaction.response.send_message("Roster is locked.", ephemeral=True); return
    if not (is_captain or is_co_captain or is_admin):
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if not is_admin and interaction.user.id not in team["players"]:
        await interaction.response.send_message("You're not on this team.", ephemeral=True); return
    if player.id == interaction.user.id and not is_admin:
        await interaction.response.send_message("Use /leave_team instead.", ephemeral=True); return
    if player.id not in team["players"]:
        await interaction.response.send_message(f"{player.mention} isn't on the team.", ephemeral=True); return
    if is_co_captain and team["captain"] == player.id:
        await interaction.response.send_message("Co-captains can't kick the captain.", ephemeral=True); return
    tpr = get_tpr(interaction.guild)
    role = interaction.guild.get_role(team["team_role"])
    if role and role in player.roles:
        await player.remove_roles(role)
    was_captain    = team["captain"]    == player.id
    was_co_captain = team["co_captain"] == player.id
    team["players"].remove(player.id)
    record_team_leave(player.id, lower)
    if was_captain:    team["captain"]    = None
    if was_co_captain: team["co_captain"] = None
    save_teams(teams)
    if tpr and tpr in player.roles and get_player_team(player.id) is None:
        await player.remove_roles(tpr)
    if was_captain:
        await revoke_general_captain_if_unneeded(interaction.guild, player.id)
    if was_co_captain:
        await revoke_general_cocaptain_if_unneeded(interaction.guild, player.id)
    await log_transaction(interaction, f"{player.mention} removed from **{team_name.title()}**.")
    await interaction.response.send_message("Done.", ephemeral=True)


@had3sbot.tree.command(name="leave_team", description="Leave your current team", guild=Server_id)
async def cmd_leave_team(interaction: discord.Interaction):
    lower = get_player_team(interaction.user.id)
    if not lower:
        await interaction.response.send_message("You're not on any team.", ephemeral=True); return
    team = teams[lower]
    if team.get("locked"):
        await interaction.response.send_message("Roster is locked.", ephemeral=True); return
    tpr = get_tpr(interaction.guild)
    role = interaction.guild.get_role(team["team_role"])
    if role and role in interaction.user.roles:
        await interaction.user.remove_roles(role)
    was_captain    = team["captain"]    == interaction.user.id
    was_co_captain = team["co_captain"] == interaction.user.id
    if was_captain:    team["captain"]    = None
    if was_co_captain: team["co_captain"] = None
    team["players"].remove(interaction.user.id)
    record_team_leave(interaction.user.id, lower)
    save_teams(teams)
    if tpr and tpr in interaction.user.roles and get_player_team(interaction.user.id) is None:
        await interaction.user.remove_roles(tpr)
    if was_captain:
        await revoke_general_captain_if_unneeded(interaction.guild, interaction.user.id)
    if was_co_captain:
        await revoke_general_cocaptain_if_unneeded(interaction.guild, interaction.user.id)
    await log_transaction(interaction, f"{interaction.user.mention} left **{lower.title()}**.")
    await interaction.response.send_message(f"You left **{lower.title()}**.", ephemeral=True)


@had3sbot.tree.command(name="assign_captain", description="Assign a captain to a team", guild=Server_id)
@app_commands.autocomplete(team_name=team_autocomplete)
async def cmd_assign_captain(interaction: discord.Interaction, team_name: str, player: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    lower = team_name.lower()
    if lower not in teams:
        await interaction.response.send_message(f"**{team_name.title()}** doesn't exist.", ephemeral=True); return
    team = teams[lower]
    if team["captain"] == player.id:
        await interaction.response.send_message(f"{player.mention} is already captain.", ephemeral=True); return
    if team.get("locked"):
        await interaction.response.send_message("Roster is locked.", ephemeral=True); return
    if player.id not in team["players"]:
        await interaction.response.send_message(f"{player.mention} isn't on the team.", ephemeral=True); return
    tpr = get_tpr(interaction.guild)
    old_captain = team["captain"]
    if tpr and tpr not in player.roles:
        await player.add_roles(tpr)
    team["captain"] = player.id
    save_teams(teams)
    await grant_general_captain(interaction.guild, player.id)
    if old_captain:
        await revoke_general_captain_if_unneeded(interaction.guild, old_captain, exclude_team=lower)
    await log_transaction(interaction, f"{player.mention} assigned captain of **{team_name.title()}**.")
    await interaction.response.send_message("Done.", ephemeral=True)


@had3sbot.tree.command(name="assign_cocaptain", description="Assign a co-captain to a team", guild=Server_id)
@app_commands.autocomplete(team_name=team_autocomplete)
async def cmd_assign_cocaptain(interaction: discord.Interaction, team_name: str, player: discord.Member):
    lower = team_name.lower()
    if lower not in teams:
        await interaction.response.send_message(f"**{team_name.title()}** doesn't exist.", ephemeral=True); return
    team = teams[lower]
    if not (team["captain"] == interaction.user.id or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if team.get("locked"):
        await interaction.response.send_message("Roster is locked.", ephemeral=True); return
    if team["co_captain"] == player.id:
        await interaction.response.send_message(f"{player.mention} is already co-captain.", ephemeral=True); return
    if player.id not in team["players"]:
        await interaction.response.send_message(f"{player.mention} isn't on the team.", ephemeral=True); return
    tpr = get_tpr(interaction.guild)
    old_co_captain = team["co_captain"]
    if tpr and tpr not in player.roles:
        await player.add_roles(tpr)
    team["co_captain"] = player.id
    save_teams(teams)
    await grant_general_cocaptain(interaction.guild, player.id)
    if old_co_captain:
        await revoke_general_cocaptain_if_unneeded(interaction.guild, old_co_captain, exclude_team=lower)
    await log_transaction(interaction, f"{player.mention} assigned co-captain of **{team_name.title()}**.")
    await interaction.response.send_message("Done.", ephemeral=True)


@had3sbot.tree.command(name="transfer_captain", description="Transfer captaincy to another player", guild=Server_id)
@app_commands.autocomplete(team_name=team_autocomplete)
async def cmd_transfer_captain(interaction: discord.Interaction, team_name: str, player: discord.Member):
    lower = team_name.lower()
    if lower not in teams:
        await interaction.response.send_message(f"**{team_name.title()}** doesn't exist.", ephemeral=True); return
    team = teams[lower]
    if not (team["captain"] == interaction.user.id or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if team.get("locked"):
        await interaction.response.send_message("Roster is locked.", ephemeral=True); return
    if team["captain"] == player.id:
        await interaction.response.send_message(f"{player.mention} is already captain.", ephemeral=True); return
    if player.id not in team["players"]:
        await interaction.response.send_message(f"{player.mention} isn't on the team.", ephemeral=True); return
    tpr = get_tpr(interaction.guild)
    old_captain = team["captain"]
    if tpr and tpr not in player.roles:
        await player.add_roles(tpr)
    team["captain"] = player.id
    save_teams(teams)
    await grant_general_captain(interaction.guild, player.id)
    if old_captain:
        await revoke_general_captain_if_unneeded(interaction.guild, old_captain, exclude_team=lower)
    await log_transaction(interaction, f"{player.mention} is now captain of **{team_name.title()}**.")
    await interaction.response.send_message(
        f"Captaincy of **{team_name.title()}** transferred to {player.mention}.", ephemeral=True)


@had3sbot.tree.command(name="invite_player", description="Invite a player to a team", guild=Server_id)
@app_commands.autocomplete(team_name=team_autocomplete)
async def cmd_invite_player(interaction: discord.Interaction, team_name: str, player: discord.Member):
    lower = team_name.lower()
    if lower not in teams:
        await interaction.response.send_message(f"**{team_name.title()}** doesn't exist.", ephemeral=True); return
    team          = teams[lower]
    is_captain    = team["captain"]    == interaction.user.id
    is_co_captain = team["co_captain"] == interaction.user.id
    is_admin      = interaction.user.guild_permissions.administrator
    if not (is_captain or is_co_captain or is_admin):
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if not is_admin and interaction.user.id not in team["players"]:
        await interaction.response.send_message("You're not on this team.", ephemeral=True); return
    if team.get("locked"):
        await interaction.response.send_message("Rosters are locked.", ephemeral=True); return
    if is_staff_member(player):
        await interaction.response.send_message(
            f"{player.mention} has the staff role and can't be invited to a team.", ephemeral=True); return
    if player.id in team["players"]:
        await interaction.response.send_message(f"{player.mention} is already on the team.", ephemeral=True); return
    if len(team["players"]) >= 12:
        await interaction.response.send_message("Team is full.", ephemeral=True); return
    if interaction.guild.get_role(team["team_role"]) is None:
        await interaction.response.send_message("Team role not found.", ephemeral=True); return
    ex = get_player_team(player.id)
    if ex:
        await interaction.response.send_message(f"{player.mention} is on **{ex.title()}**.", ephemeral=True); return
    if any(i["team_name"] == lower for i in pending_invites.get(player.id, [])):
        await interaction.response.send_message(f"{player.mention} already has a pending invite.", ephemeral=True); return
    pending_invites.setdefault(player.id, []).append({"team_name": lower, "inviter_id": interaction.user.id})
    save_invites(pending_invites)
    await interaction.response.send_message(f"Invite sent to {player.mention}.", ephemeral=True)


@had3sbot.tree.command(name="cancel_invite", description="Cancel a pending invite you sent to a player", guild=Server_id)
@app_commands.autocomplete(team_name=team_autocomplete)
@app_commands.describe(team_name="Your team", player="Player whose invite to cancel")
async def cmd_cancel_invite(interaction: discord.Interaction, team_name: str, player: discord.Member):
    lower = team_name.lower()
    if lower not in teams:
        await interaction.response.send_message(f"**{team_name.title()}** doesn't exist.", ephemeral=True); return
    team = teams[lower]
    if team.get("locked"):
        await interaction.response.send_message("Roster is locked.", ephemeral=True); return
    is_captain    = team["captain"]    == interaction.user.id
    is_co_captain = team["co_captain"] == interaction.user.id
    is_admin      = interaction.user.guild_permissions.administrator
    if not (is_captain or is_co_captain or is_admin):
        await interaction.response.send_message("No permission.", ephemeral=True); return
    invites = pending_invites.get(player.id, [])
    before  = len(invites)
    pending_invites[player.id] = [i for i in invites if i["team_name"] != lower]
    if len(pending_invites[player.id]) == before:
        await interaction.response.send_message(f"No pending invite from **{team_name.title()}** to {player.mention}.", ephemeral=True); return
    save_invites(pending_invites)
    await interaction.response.send_message(
        f"Invite to {player.mention} from **{team_name.title()}** has been cancelled.", ephemeral=True)


@had3sbot.tree.command(name="check_invites", description="View your pending team invites", guild=Server_id)
async def cmd_check_invites(interaction: discord.Interaction):
    invites = pending_invites.get(interaction.user.id, [])
    if not invites:
        await interaction.response.send_message("No pending invites.", ephemeral=True); return
    await interaction.response.send_message(
        content="## 📤 Your pending invites\n> Click a team to accept or decline:",
        view=MyInvitesView(interaction.user, invites), ephemeral=True)


@had3sbot.tree.command(name="player_info", description="View a player's profile", guild=Server_id)
@is_premium()
async def cmd_player_info(interaction: discord.Interaction, player: discord.Member):
    team_key = get_player_team(player.id)
    if team_key:
        team      = teams[team_key]
        team_name = team_key.title()
        w, l, d   = team.get("wins",0), team.get("losses",0), team.get("draws",0)
        role_label = ("👑 Captain" if team["captain"] == player.id
                      else "⭐ Co-Captain" if team["co_captain"] == player.id
                      else "🎮 Player")
    else:
        team_name = "Free Agent"; w = l = d = 0; role_label = "Not on a team"
    history  = player_history.get(str(player.id), [])
    hist_str = "\n".join(
        f"{'Joined' if e['action']=='joined' else 'Left'} **{e['team'].title()}** on `{e['timestamp'][:10]}`"
        for e in reversed(history)) or "No history on record."
    content = f"# 🎮 {player.display_name}\n>>> **Team History:** {team_name}\n**Role:** {role_label}\n**Record:** {w}W / {l}L / {d}D\n## 📋 Team History\n{hist_str}"
    await interaction.response.send_message(content, ephemeral = True)


@had3sbot.tree.command(name="create_seeding", description="Create a seeding round", guild=Server_id)
@is_premium()
@app_commands.describe(win_points="Points per win", loss_points="Points per loss")
async def cmd_create_seeding(interaction: discord.Interaction, win_points: int, loss_points: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if not teams:
        await interaction.response.send_message("No teams yet.", ephemeral=True); return
    for n in teams:
        teams[n]["wins"] = teams[n]["losses"] = teams[n]["draws"] = 0
    save_teams(teams)
    points = {n: 0 for n in teams}
    order  = sorted(points, key=lambda k: points[k], reverse=True)
    content = build_seeding_content(order, points=points)
    await interaction.response.send_message("Done.", ephemeral=True)
    message = await interaction.channel.send(content)
    seeding.update({
        "created_by": interaction.user.id, "created_at": discord.utils.utcnow().isoformat(),
        "order": order, "points": points, "win_points": win_points, "loss_points": loss_points,
        "channel_id": interaction.channel.id, "message_id": message.id, "locked": False,
    })
    save_seeding(seeding)


@had3sbot.tree.command(name="edit_seeding", description="Edit a team's wins and/or points in seeding", guild=Server_id)
@is_premium()
@app_commands.autocomplete(team_name=seeding_team_autocomplete)
@app_commands.describe(team_name="Team to edit", wins="Wins to add (negative to subtract)", points="Points to add (negative to subtract)")
async def cmd_edit_seeding(interaction: discord.Interaction, team_name: str, wins: int = 0, points: int = 0):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if not seeding or not seeding.get("order"):
        await interaction.response.send_message("No seeding active.", ephemeral=True); return
    if seeding.get("locked"):
        await interaction.response.send_message("Seeding is locked.", ephemeral=True); return
    lower = team_name.lower()
    if lower not in seeding["order"]:
        await interaction.response.send_message(f"**{team_name.title()}** not in seeding.", ephemeral=True); return
    if wins == 0 and points == 0:
        await interaction.response.send_message("Provide at least one of `wins` or `points`.", ephemeral=True); return

    async with seeding_lock:
        if wins != 0 and lower in teams:
            if wins > 0:
                teams[lower]["wins"] = teams[lower].get("wins", 0) + wins
            else:
                teams[lower]["wins"] = max(0, teams[lower].get("wins", 0) + wins)
            save_teams(teams)
        pts = seeding.get("points", {})
        if points != 0:
            pts[lower] = max(0, pts.get(lower, 0) + points)
        order = sorted(pts, key=lambda k: pts[k], reverse=True)
        seeding["order"]  = order
        seeding["points"] = pts
        save_seeding(seeding)

    original = await get_seeding_message(interaction.guild)
    if original:
        new_content = build_seeding_content(order, points=pts)
        await original.edit(content=new_content)

    changes = []
    if wins != 0:
        changes.append(f"{'➕' if wins > 0 else '➖'} **{abs(wins)} win(s)** {'added to' if wins > 0 else 'removed from'} **{team_name.title()}**")
    if points != 0:
        changes.append(f"{'➕' if points > 0 else '➖'} **{abs(points)} point(s)** {'added to' if points > 0 else 'removed from'} **{team_name.title()}**")

    result_msg = "\n".join(changes)
    if interaction.response.is_done():
        await interaction.followup.send(result_msg, ephemeral=True)
    else:
        await interaction.response.send_message(result_msg, ephemeral=True)


@had3sbot.tree.command(name="end_seeding", description="End the seeding round", guild=Server_id)
@is_premium()
@app_commands.describe(qualifiers="Number of teams that advance")
async def cmd_end_seeding(interaction: discord.Interaction, qualifiers: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if not seeding or not seeding.get("order"):
        await interaction.response.send_message("No seeding yet.", ephemeral=True); return
    if seeding.get("locked"):
        await interaction.response.send_message("Seeding already ended.", ephemeral=True); return
    order = seeding["order"]
    if not 1 <= qualifiers <= len(order):
        await interaction.response.send_message(f"Must be 1–{len(order)}.", ephemeral=True); return
    seeding["locked"]     = True
    seeding["qualifiers"] = qualifiers
    save_seeding(seeding)
    pts   = seeding.get("points", {})
    content = build_seeding_content(order, points=pts, ended=True, qualifiers=qualifiers)
    msg = await get_seeding_message(interaction.guild)
    if msg:
        await msg.edit(content=content)
        await interaction.response.send_message("Seeding ended.", ephemeral=True)
    else:
        await interaction.response.send_message("Original not found, posting new.", ephemeral=True)
        new = await interaction.channel.send(content)
        seeding["channel_id"] = interaction.channel.id
        seeding["message_id"] = new.id
        save_seeding(seeding)


# ── /set_scrim ────────────────────────────────────────────────────────────────
@had3sbot.tree.command(name="set_scrim", description="Set a time and date for a scrim", guild=Server_id)
@is_premium()
@app_commands.autocomplete(first_team=team_autocomplete, second_team=team_autocomplete)
async def cmd_set_scrim(interaction: discord.Interaction, time: str, date: str,
                        first_team: str, second_team: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    if not validate_time(time):
        await interaction.response.send_message(
            "❌ Invalid time format. Use something like `7:30 PM` or `19:30`.", ephemeral=True); return
    if not validate_date(date):
        await interaction.response.send_message(
            "❌ Invalid date format. Use something like `2026-06-29`, `6/29/2026`, or `June 29th, 2026`.", ephemeral=True); return
    if first_team.lower() == second_team.lower():
        await interaction.response.send_message("Teams can't be the same.", ephemeral=True); return
    if first_team.lower() not in teams:
        await interaction.response.send_message(f"**{first_team.title()}** doesn't exist.", ephemeral=True); return
    if second_team.lower() not in teams:
        await interaction.response.send_message(f"**{second_team.title()}** doesn't exist.", ephemeral=True); return
    t1l, t2l = first_team.lower(), second_team.lower()
    for s in scrims_schedule:
        if (s["team1"].lower() == t1l and s["team2"].lower() == t2l) or \
           (s["team1"].lower() == t2l and s["team2"].lower() == t1l):
            await interaction.response.send_message(
                f"A scrim between **{first_team.title()}** and **{second_team.title()}** already exists.",
                ephemeral=True); return

    await interaction.response.send_message("Scrim created.", ephemeral=True)
    key = make_scrim_key(first_team, second_team)
    await post_scrim_to_channels(interaction.guild, key, time, date, first_team.title(), second_team.title())
    scrims_schedule.append({"time": time, "date": date,
                             "team1": first_team.title(), "team2": second_team.title(),
                             "datetime_utc": parse_scrim_datetime(time, date),
                             "league_code": f"SCL{random.randint(100, 999)}"})
    save_scrims(scrims_schedule)


# ── /reschedule_scrim ─────────────────────────────────────────────────────────
@had3sbot.tree.command(name="reschedule_scrim", description="Change the time/date of an existing scrim", guild=Server_id)
@is_premium()
@app_commands.autocomplete(scrim=scrim_autocomplete)
@app_commands.describe(scrim="The scrim to reschedule", new_time="New time", new_date="New date")
async def cmd_reschedule_scrim(interaction: discord.Interaction, scrim: str, new_time: str, new_date: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    parts = scrim.split("|")
    if len(parts) != 4:
        await interaction.response.send_message("Invalid scrim selection.", ephemeral=True); return
    team1, team2, old_time, old_date = parts
    if not validate_time(new_time):
        await interaction.response.send_message(
            "Invalid time format. Use something like `7:30 PM` or `19:30`.", ephemeral=True); return
    if not validate_date(new_date):
        await interaction.response.send_message(
            "Invalid date format. Use something like `2026-06-29`, `6/29/2026`, or `June 29th, 2026`.", ephemeral=True); return

    if not update_schedule_entry_time(team1, team2, new_time, new_date):
        await interaction.response.send_message("Scrim not found in schedule.", ephemeral=True); return

    key = make_scrim_key(team1, team2)
    await update_posted_scrim_time(interaction.guild, key, new_time, new_date)

    # Notify the private scrim channel, if one exists for this matchup
    t1l, t2l = team1.lower(), team2.lower()
    scrim_ch_id = next(
        (cid for cid, d in scrim_channels.items()
         if (d["t1_key"] == t1l and d["t2_key"] == t2l) or
            (d["t1_key"] == t2l and d["t2_key"] == t1l)), None)
    scrim_ch = interaction.guild.get_channel(scrim_ch_id) if scrim_ch_id else None
    if scrim_ch:
        try:
            await scrim_ch.send(
                f"# 🔁 Scrim Rescheduled\n"
                f"> New time: **{new_time}** on **{new_date}**"
            )
        except Exception:
            pass

    await update_scrim_channel_emoji(interaction.guild, t1l, t2l, "⏳")

    await interaction.response.send_message(
        f"# ✅ Scrim rescheduled!\n"
        f"> **{team1.title()}** vs **{team2.title()}**\n"
        f"> New time: **{new_time}** on **{new_date}**",
        ephemeral=True)


# ── /suggest_time ─────────────────────────────────────────────────────────────
@had3sbot.tree.command(name="suggest_time", description="Propose a scrim time in a scrim channel", guild=Server_id)
@is_premium()
async def cmd_suggest_time(interaction: discord.Interaction, time: str, date: str):
    channel_data = scrim_channels.get(interaction.channel.id)
    if not channel_data:
        await interaction.response.send_message("Only usable in a scrim channel.", ephemeral=True); return
    if not validate_time(time):
        await interaction.response.send_message(
            "❌ Invalid time format. Use something like `7:30 PM` or `19:30`.", ephemeral=True); return
    if not validate_date(date):
        await interaction.response.send_message(
            "❌ Invalid date format. Use something like `2026-06-29`, `6/29/2026`, or `June 29th, 2026`.", ephemeral=True); return
    t1_key = channel_data["t1_key"]
    t2_key = channel_data["t2_key"]
    if t1_key not in teams or t2_key not in teams:
        await interaction.response.send_message("One or both teams no longer exist.", ephemeral=True); return
    team1 = teams[t1_key]
    team2 = teams[t2_key]
    uid   = interaction.user.id
    is_t1 = uid in (team1["captain"], team1["co_captain"])
    is_t2 = uid in (team2["captain"], team2["co_captain"])
    if not (is_t1 or is_t2):
        await interaction.response.send_message("Only captains can propose a time.", ephemeral=True); return
    other_captain_id = team2["captain"] if is_t1 else team1["captain"]
    other_team_name  = t2_key if is_t1 else t1_key
    if not other_captain_id:
        await interaction.response.send_message(f"**{other_team_name.title()}** has no captain.", ephemeral=True); return

    proposal_key = f"proposal:{t1_key}:{t2_key}:{interaction.id}"
    view = ScrimProposalView(t1_key, t2_key, time, date, uid, other_captain_id, proposal_key=proposal_key)
    pending_proposals[proposal_key] = {
        "t1_key": t1_key, "t2_key": t2_key,
        "time": time, "date": date,
        "proposer_id": uid, "other_captain_id": other_captain_id,
    }
    save_proposals(pending_proposals)
    had3sbot.add_view(view)

    await interaction.response.send_message("Proposal sent!", ephemeral=True)
    content = (
        f"<@{other_captain_id}>\n"
        f"# 🕐 Scrim Time Proposal\n"
        f"> **{t1_key.title()}** vs **{t2_key.title()}**\n\n"
        f"> **Proposed Time:** {time}\n**Proposed Date:** {date}\n\n"
        f"> *Proposed by {interaction.user.mention}*"
    )
    await interaction.channel.send(content, view=view)


# ── /set_time ─────────────────────────────────────────────────────────────────
@had3sbot.tree.command(name="set_time", description="Forcibly set a scrim time (Admin only)", guild=Server_id)
@is_premium()
async def cmd_set_time(interaction: discord.Interaction, time: str, date: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    channel_data = scrim_channels.get(interaction.channel.id)
    if not channel_data:
        await interaction.response.send_message("Channel not registered.", ephemeral=True); return
    if not validate_time(time):
        await interaction.response.send_message(
            "❌ Invalid time format. Use something like `7:30 PM` or `19:30`.", ephemeral=True); return
    if not validate_date(date):
        await interaction.response.send_message(
            "❌ Invalid date format. Use something like `2026-06-29`, `6/29/2026`, or `June 29th, 2026`.", ephemeral=True); return
    t1_key = channel_data["t1_key"]
    t2_key = channel_data["t2_key"]
    if t1_key not in teams or t2_key not in teams:
        await interaction.response.send_message("One or both teams no longer exist.", ephemeral=True); return

    key = make_scrim_key(t1_key, t2_key)
    updated = await update_posted_scrim_time(interaction.guild, key, time, date)
    if updated:
        update_schedule_entry_time(t1_key.title(), t2_key.title(), time, date)
        await interaction.response.send_message(f"Scrim updated to **{date}** at **{time}**!", ephemeral=True)
    else:
        await interaction.response.send_message(f"Scrim set for **{date}** at **{time}**!", ephemeral=True)
        await post_scrim_to_channels(interaction.guild, key, time, date, t1_key.title(), t2_key.title())
        scrims_schedule.append({"time": time, "date": date, "team1": t1_key.title(), "team2": t2_key.title(),
                                 "datetime_utc": parse_scrim_datetime(time, date),
                                 "league_code": f"SCL{random.randint(100, 999)}"})
        save_scrims(scrims_schedule)
    await update_scrim_channel_emoji(interaction.guild, t1_key, t2_key, "⏳")


# ── Shared forfeit logic ──────────────────────────────────────────────────────
async def _process_forfeit(interaction, team1, team2, forfeiting_team, reason, auto=False):
    fkey   = forfeiting_team.lower()
    winner = (team2 if fkey == team1.lower() else team1).lower()
    loser  = fkey
    key    = make_scrim_key(team1, team2)
    t1_key = team1.lower()
    t2_key = team2.lower()

    forfeit_content = (
        f"# 🚫 Scrim Forfeited\n"
        f"## **Official Scrim:**\n"
        f"> **First Team:** {team1.title()}\n"
        f"> **Second Team:** {team2.title()}\n"
        f"> **🏆 Winner:** {winner.title()} (by {'auto-' if auto else ''}forfeit)\n"
        f"> **❌ Forfeit:** {loser.title()}\n**Reason:** {reason}"
    )

    msg = await get_scrim_message(interaction.guild, key)
    if msg:
        try:
            await msg.edit(content=forfeit_content, view=None)
        except Exception:
            pass
        mirror = await get_mirror_message(interaction.guild, key)
        if mirror:
            try:
                await mirror.edit(content=forfeit_content)
            except Exception:
                pass
        scrim_messages.pop(key, None)
        scrim_message_ids.pop(key, None)
        save_scrim_messages(scrim_message_ids)

    new_schedule = [s for s in scrims_schedule
                    if not (s["team1"].lower() == team1.lower() and s["team2"].lower() == team2.lower())]
    scrims_schedule.clear()
    scrims_schedule.extend(new_schedule)
    save_scrims(scrims_schedule)

    if winner in teams:
        teams[winner]["wins"]   = teams[winner].get("wins", 0) + 1
    if loser in teams:
        teams[loser]["losses"]  = teams[loser].get("losses", 0) + 1
    save_teams(teams)
    await apply_seeding_result(interaction, winner, loser,
                               f"Updated after {loser.title()} forfeited vs {winner.title()}")

    label = "Auto-Forfeit" if auto else "Scrim Forfeit"
    result_content = (
        f"# 🚫 {label}\n>>> **{team1.title()}** vs **{team2.title()}**\n\n"
        f"**🏆 Winner:** {winner.title()} *(by {'auto-' if auto else ''}forfeit)*\n"
        f"**❌ Forfeited by:** {loser.title()}\n**Reason:** {reason}\n\n"
        f"-# {'Auto-forfeit' if auto else 'Forfeit'} logged by {interaction.user.display_name}"
    )
    scrims_ch = interaction.guild.get_channel(Scrims_channel)
    if scrims_ch:
        try:
            await scrims_ch.send(result_content)
        except Exception:
            pass
    await update_scrim_channel_emoji(interaction.guild, t1_key, t2_key, "☑️")

    # ── Close out the private scrim channel, same as /end_scrim ──────────────
    stale = [cid for cid, d in scrim_channels.items()
             if (d["t1_key"] == t1_key and d["t2_key"] == t2_key)
             or (d["t1_key"] == t2_key and d["t2_key"] == t1_key)]
    for cid in stale:
        ch = interaction.guild.get_channel(cid)
        if ch:
            try:
                for tkey in (t1_key, t2_key):
                    role = interaction.guild.get_role(teams.get(tkey, {}).get("team_role"))
                    if role:
                        await ch.set_permissions(role, view_channel=False)
            except Exception:
                pass

            async def do_delete_channel(confirm_interaction: discord.Interaction, channel=ch):
                try:
                    await channel.delete(reason=f"Scrim channel closed by {interaction.user}")
                except discord.NotFound:
                    pass
                except discord.Forbidden:
                    await confirm_interaction.followup.send("Missing permission to delete this channel.", ephemeral=True)

            try:
                await ch.send(
                    "# 🔒 Scrim Channel Closed\n"
                    ">>> This scrim has ended and team access has been revoked.\n"
                    "Would you like to delete this channel now, or keep it for reference?",
                    view=ConfirmView(do_delete_channel, label="Delete Channel"))
            except Exception:
                pass
        scrim_channels.pop(cid, None)
    save_scrim_channels(scrim_channels)


# ── /end_scrim ────────────────────────────────────────────────────────────────
@had3sbot.tree.command(name="end_scrim", description="End and record the score of a scrim", guild=Server_id)
@is_premium()
@app_commands.autocomplete(scrim=scrim_autocomplete)
@app_commands.describe(scrim="The scrim to end", score1="Score for the first team", score2="Score for the second team", notes="Optional notes")
async def cmd_end_scrim(interaction: discord.Interaction, scrim: str, score1: int, score2: int, notes: str = ""):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    parts = scrim.split("|")
    if len(parts) != 4:
        await interaction.response.send_message("Invalid scrim selection.", ephemeral=True); return
    team1, team2, time, date = parts
    t1_key = team1.lower()
    t2_key = team2.lower()

    if score1 < 0 or score2 < 0:
        await interaction.response.send_message("Scores can't be negative.", ephemeral=True); return
    if score1 > MAX_SCORE or score2 > MAX_SCORE:
        await interaction.response.send_message(f"Scores can't exceed {MAX_SCORE}.", ephemeral=True); return

    key = make_scrim_key(team1, team2)
    msg = await get_scrim_message(interaction.guild, key)

    result_str = (f"{team1.title()} wins" if score1 > score2
                  else f"{team2.title()} wins" if score2 > score1 else "Draw")
    completed_content = (
        "# ✅ Scrim Completed\n"
        "> ## **Official Scrim For SCL:**\n\n"
        f"> **First Team:** {team1.title()}\n**Second Team:** {team2.title()}\n\n"
        f"> **Result:** {result_str} **{score1} - {score2}**"
    )

    if msg:
        try:
            await msg.edit(content=completed_content, view=None)
        except Exception:
            pass
        mirror = await get_mirror_message(interaction.guild, key)
        if mirror:
            try:
                await mirror.edit(content=completed_content)
            except Exception:
                pass
        scrim_messages.pop(key, None)
        scrim_message_ids.pop(key, None)
        save_scrim_messages(scrim_message_ids)


    new_schedule = [s for s in scrims_schedule
                    if not (s["team1"].lower() == t1_key and s["team2"].lower() == t2_key)]
    scrims_schedule.clear()
    scrims_schedule.extend(new_schedule)
    save_scrims(scrims_schedule)

    if score1 == score2:
        for t in (t1_key, t2_key):
            if t in teams:
                teams[t]["draws"] = teams[t].get("draws", 0) + 1
        save_teams(teams)
        if seeding and seeding.get("order") and not seeding.get("locked"):
            loss_pts = seeding.get("loss_points", 0)
            pts      = seeding.get("points", {})
            updated  = False
            for t in (t1_key, t2_key):
                if t in pts:
                    pts[t] = pts.get(t, 0) + loss_pts
                    updated = True
            if updated:
                order = sorted(pts, key=lambda k: pts[k], reverse=True)
                seeding["order"]  = order
                seeding["points"] = pts
                save_seeding(seeding)
                seed_msg = await get_seeding_message(interaction.guild)
                if seed_msg:
                    await seed_msg.edit(content=build_seeding_content(order, points=pts))
    else:
        winner = (t1_key if score1 > score2 else t2_key)
        loser  = (t2_key if score1 > score2 else t1_key)
        if winner in teams:
            teams[winner]["wins"]   = teams[winner].get("wins", 0) + 1
        if loser in teams:
            teams[loser]["losses"]  = teams[loser].get("losses", 0) + 1
        save_teams(teams)
        await apply_seeding_result(interaction, winner, loser,
                                   f"Updated after {team1.title()} vs {team2.title()}")

    outcome = "🤝 Draw" if score1 == score2 else f"🏆 {team1.title() if score1 > score2 else team2.title()} Wins"
    result_content = (
        "# 🏆 Scrim Result\n"
        f">>> Scrim: **{team1.title()}** vs **{team2.title()}**\n"
        f"Score: **{score1} - {score2}**\n Result: **{outcome}**"
    )
    if notes:
        result_content += f"\n### Notes:\n{notes}"
    result_content += "\n\n-# Good Game!"
    result_ch = interaction.guild.get_channel(Scrim_score_channel)
    await interaction.response.send_message("Scrim score logged.", ephemeral=True)
    if result_ch:
        await result_ch.send(result_content)

    await update_scrim_channel_emoji(interaction.guild, t1_key, t2_key, "✅")
    stale = [cid for cid, d in scrim_channels.items()
             if (d["t1_key"] == t1_key and d["t2_key"] == t2_key)
             or (d["t1_key"] == t2_key and d["t2_key"] == t1_key)]
    for cid in stale:
        ch = interaction.guild.get_channel(cid)
        if ch:
            try:
                for tkey in (t1_key, t2_key):
                    role = interaction.guild.get_role(teams.get(tkey, {}).get("team_role"))
                    if role:
                        await ch.set_permissions(role, view_channel=False)
            except Exception:
                pass

            async def do_delete_channel(confirm_interaction: discord.Interaction, channel=ch):
                try:
                    await channel.delete(reason=f"Scrim channel closed by {interaction.user}")
                except discord.NotFound:
                    pass
                except discord.Forbidden:
                    await confirm_interaction.followup.send("Missing permission to delete this channel.", ephemeral=True)

            try:
                await ch.send(
                    "# 🔒 Scrim Channel Closed\n"
                    ">>> This scrim has ended and team access has been revoked.\n"
                    "Would you like to delete this channel now, or keep it for reference?",
                    view=ConfirmView(do_delete_channel, label="Delete Channel"))
            except Exception:
                pass
        scrim_channels.pop(cid, None)
    save_scrim_channels(scrim_channels)


# ── /check_scrims ─────────────────────────────────────────────────────────────
@had3sbot.tree.command(name="check_scrims", description="View upcoming scrims", guild=Server_id)
@is_premium()
async def cmd_check_scrims(interaction: discord.Interaction):
    if not scrims_schedule:
        await interaction.response.send_message("No scrims scheduled.", ephemeral=True); return
    lines = "\n".join(f"• **{s['team1']}** vs **{s['team2']}**\n  {s['date']} at {s['time']}"
                      for s in scrims_schedule)
    await interaction.response.send_message(f"# Upcoming Scrims:\n>>> {lines}", ephemeral=True)





# ── /create_scrim_channel ─────────────────────────────────────────────────────
@had3sbot.tree.command(name="create_scrim_channel", description="Create a private scrim channel", guild=Server_id)
@is_premium()
@app_commands.autocomplete(first_team=team_autocomplete, second_team=team_autocomplete, category_name=category_autocomplete)
@app_commands.describe(first_team="First team", second_team="Second team", category_name="Category (default: Scheduling)")
async def cmd_create_scrim_channel(interaction: discord.Interaction, first_team: str, second_team: str, category_name: str = "Scheduling"):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    t1, t2 = first_team.lower(), second_team.lower()
    if t1 == t2:
        await interaction.response.send_message("Teams can't be the same.", ephemeral=True); return
    if t1 not in teams:
        await interaction.response.send_message(f"**{first_team.title()}** doesn't exist.", ephemeral=True); return
    if t2 not in teams:
        await interaction.response.send_message(f"**{second_team.title()}** doesn't exist.", ephemeral=True); return
    for s in scrims_schedule:
        if (s["team1"].lower() == t1 and s["team2"].lower() == t2) or \
           (s["team1"].lower() == t2 and s["team2"].lower() == t1):
            await interaction.response.send_message(
                f"A scrim between **{first_team.title()}** and **{second_team.title()}** already exists.",
                ephemeral=True); return

    await interaction.response.defer(ephemeral=True)
    category = discord.utils.get(interaction.guild.categories, name=category_name)
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.guild.me:           discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    for tkey in (t1, t2):
        role = interaction.guild.get_role(teams[tkey]["team_role"])
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    for role_id in (Commentator_role, Caster_role, Referee_role):
        role = interaction.guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)

    if staff_role:
        role = interaction.guild.get_role(staff_role)
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True, read_message_history=True)

    for role in interaction.guild.roles:
        if role.permissions.administrator:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)

    try:
        channel = await interaction.guild.create_text_channel(
            name=f"「⚔️」{t1}-vs-{t2}", category=category, overwrites=overwrites,
            topic=f"Private scrim channel: {first_team.title()} vs {second_team.title()}")

    except discord.HTTPException as e:
        await interaction.followup.send(f"Failed to create the channel: {e}", ephemeral=True)
        return

    SCRIM_CHANNEL_DEADLINE_DAYS = 4  # adjust as needed

    def build_scrim_channel_welcome(team1_role: discord.Role | None, team2_role: discord.Role | None,
                                    team1_name: str, team2_name: str) -> str:
        pings = " ".join(r.mention for r in (team1_role, team2_role) if r)
        return (
            (pings + "\n" if pings else "") +
            f"# 🏓 Scrim Channel\n"
            f"> This is your private scrim scheduling channel.\n"
            f"> You have **{SCRIM_CHANNEL_DEADLINE_DAYS} days** to complete your scrim.\n"
            f"> Type `/suggest_time` to suggest a time to the other captain.\n"
            f"> To forfeit, type `/forfeit_scrim`.\n\n"
            f"**Good luck to both teams!**"
        )

    scrim_channels[channel.id] = {"t1_key": t1, "t2_key": t2}
    save_scrim_channels(scrim_channels)

    team1_role = interaction.guild.get_role(teams[t1]["team_role"])
    team2_role = interaction.guild.get_role(teams[t2]["team_role"])
    try:
        await channel.send(build_scrim_channel_welcome(team1_role, team2_role, first_team.title(), second_team.title()))
    except Exception as e:
        print(f"[create_scrim_channel] Failed to send welcome message: {e}")

    await interaction.followup.send(
        f"✅ Scrim channel created: {channel.mention}\n"
        f"-# The officials post and team pings for referees/casters will happen once a time is set with `/suggest_time` or `/set_time`.",
        ephemeral=True)
    


# ── /forfeit_scrim ────────────────────────────────────────────────────────────
@had3sbot.tree.command(name="forfeit_scrim", description="Forfeit a scrim (use inside the scrim channel)", guild=Server_id)
@is_premium()
@app_commands.autocomplete(forfeiting_team=team_autocomplete)
@app_commands.describe(forfeiting_team="The team that is forfeiting", reason="Reason for forfeit")
async def cmd_forfeit_scrim(interaction: discord.Interaction, forfeiting_team: str, reason: str = "No reason provided"):
    uid          = interaction.user.id
    is_admin     = interaction.user.guild_permissions.administrator
    channel_data = scrim_channels.get(interaction.channel.id)
    if not channel_data:
        await interaction.response.send_message("This command must be used inside a scrim channel.", ephemeral=True); return
    t1_key = channel_data["t1_key"]
    t2_key = channel_data["t2_key"]
    fkey   = forfeiting_team.lower()
    if fkey not in (t1_key, t2_key):
        await interaction.response.send_message(
            f"**{forfeiting_team.title()}** isn't in this scrim channel.", ephemeral=True); return
    if not is_admin:
        forfeiting_team_data = teams.get(fkey, {})
        is_cap_of_forfeiting = (
            forfeiting_team_data.get("captain") == uid or
            forfeiting_team_data.get("co_captain") == uid)
        if not is_cap_of_forfeiting:
            await interaction.response.send_message("You can only forfeit your own team.", ephemeral=True); return
    await interaction.response.send_message("Forfeit logged.", ephemeral=True)
    await _process_forfeit(interaction, t1_key.title(), t2_key.title(), forfeiting_team.title(), reason, auto=False)


# ── /autoforfeit_scrim ────────────────────────────────────────────────────────
@had3sbot.tree.command(name="autoforfeit_scrim", description="Auto-forfeit a scrim (Admin only, use inside the scrim channel)", guild=Server_id)
@is_premium()
@app_commands.autocomplete(forfeiting_team=team_autocomplete)
@app_commands.describe(forfeiting_team="The team being auto-forfeited", reason="Reason for auto-forfeit")
async def cmd_autoforfeit_scrim(interaction: discord.Interaction, forfeiting_team: str, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    channel_data = scrim_channels.get(interaction.channel.id)
    if not channel_data:
        await interaction.response.send_message("This command must be used inside a scrim channel.", ephemeral=True); return
    t1_key = channel_data["t1_key"]
    t2_key = channel_data["t2_key"]
    fkey   = forfeiting_team.lower()
    if fkey not in (t1_key, t2_key):
        await interaction.response.send_message(
            f"**{forfeiting_team.title()}** isn't in this scrim channel.", ephemeral=True); return
    await interaction.response.send_message("Auto-forfeit logged.", ephemeral=True)
    await _process_forfeit(interaction, t1_key.title(), t2_key.title(), forfeiting_team.title(), reason, auto=True)


# ── /send_files ───────────────────────────────────────────────────────────────
@had3sbot.tree.command(name="send_files", description="Sends all JSON data files.", guild=Server_id)
async def send_files(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No permission.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    files = [discord.File(p, filename=os.path.basename(p))
             for p in (Team_file, Scrim_file, Scrim_message_file,
                       Invite_file, Seeding_file, Scrim_channel_file,
                       Player_history_file, Proposals_file)
             if os.path.exists(p)]
    if not files:
        await interaction.followup.send("No data files found.", ephemeral=True); return
    await interaction.followup.send(
        f"# SCL Data Backup\n>>> **{len(files)} files** attached.\n*Keep these safe!*",
        files=files, ephemeral=True)


# ── Run ───────────────────────────────────────────────────────────────────────
had3sbot.run(os.getenv("TOKEN"))
