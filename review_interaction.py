import discord
from database import Database

REACTION_TYPES = {
    'fire':     {'emoji': '\U0001f525', 'label': '존나 잘썼노'},
    'clap':     {'emoji': '\U0001f44f', 'label': '잘썼노'},
    'thumbsup': {'emoji': '\U0001f44d', 'label': '좋아요'},
    'laugh':    {'emoji': '\U0001f602', 'label': '재밌어요'},
    'hmm':      {'emoji': '\U0001f914', 'label': '뭐하냐?'},
    'skull':    {'emoji': '\U0001f480', 'label': '병신'},
}


def _make_reaction_button(rtype, info, count=0):
    label = f"{info['label']}" if count == 0 else f"{info['label']} {count}"
    return discord.ui.Button(
        style=discord.ButtonStyle.secondary,
        label=label,
        emoji=info['emoji'],
        custom_id=f"review_reaction:{rtype}",
        row=0 if rtype in ('fire', 'clap', 'thumbsup') else 1,
    )


class ReviewReactionView(discord.ui.View):
    """Persistent view for review reactions and comments."""

    def __init__(self):
        super().__init__(timeout=None)
        self._build_buttons()

    def _build_buttons(self):
        for rtype, info in REACTION_TYPES.items():
            btn = _make_reaction_button(rtype, info)
            btn.callback = self._make_reaction_callback(rtype)
            self.add_item(btn)

        # Comment buttons (row 2)
        comment_btn = discord.ui.Button(
            style=discord.ButtonStyle.primary,
            label="코멘트",
            emoji="\U0001f4ac",
            custom_id="review_comment:write",
            row=2,
        )
        comment_btn.callback = self._comment_write_callback
        self.add_item(comment_btn)

        view_btn = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="코멘트 보기",
            emoji="\U0001f4cb",
            custom_id="review_comment:view",
            row=2,
        )
        view_btn.callback = self._comment_view_callback
        self.add_item(view_btn)

    def update_counts(self, reaction_counts, comment_count=0):
        """Update button labels with counts."""
        for child in self.children:
            if not isinstance(child, discord.ui.Button) or not child.custom_id:
                continue

            if child.custom_id.startswith("review_reaction:"):
                rtype = child.custom_id.split(":")[1]
                info = REACTION_TYPES[rtype]
                count = reaction_counts.get(rtype, 0)
                child.label = f"{info['label']}" if count == 0 else f"{info['label']} {count}"

            elif child.custom_id == "review_comment:view":
                child.label = "코멘트 보기" if comment_count == 0 else f"코멘트 보기 {comment_count}"

    def _make_reaction_callback(self, rtype):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()

            db = interaction.client.db
            review = db.get_review_by_message_id(interaction.message.id)
            if not review:
                await interaction.followup.send(
                    "❌ 이 메시지에 연결된 리뷰를 찾을 수 없습니다.", ephemeral=True
                )
                return

            action, _ = db.toggle_reaction(
                review['id'], interaction.user.id,
                interaction.user.display_name, rtype
            )
            if action is None:
                await interaction.followup.send(
                    "❌ 반응 처리 중 오류가 발생했습니다.", ephemeral=True
                )
                return

            counts = db.get_reaction_counts(review['id'])
            comment_count = db.get_comment_count(review['id'])
            self.update_counts(counts, comment_count)
            await interaction.message.edit(view=self)

        return callback

    async def _comment_write_callback(self, interaction: discord.Interaction):
        db = interaction.client.db
        review = db.get_review_by_message_id(interaction.message.id)
        if not review:
            await interaction.response.send_message(
                "❌ 이 메시지에 연결된 리뷰를 찾을 수 없습니다.", ephemeral=True
            )
            return

        modal = ReviewCommentModal(review['id'], interaction.message)
        await interaction.response.send_modal(modal)

    async def _comment_view_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        db = interaction.client.db
        review = db.get_review_by_message_id(interaction.message.id)
        if not review:
            await interaction.followup.send(
                "❌ 이 메시지에 연결된 리뷰를 찾을 수 없습니다.", ephemeral=True
            )
            return

        comments = db.get_comments(review['id'])
        if not comments:
            await interaction.followup.send(
                "💬 아직 코멘트가 없습니다.", ephemeral=True
            )
            return

        lines = []
        for c in comments:
            ts = c['created_at'].strftime("%m/%d %H:%M")
            lines.append(f"**{c['username']}** ({ts}): {c['content']}")

        text = "\n".join(lines)
        if len(text) > 1900:
            text = text[:1900] + "\n..."

        await interaction.followup.send(
            f"💬 **코멘트 ({len(comments)}개)**\n\n{text}", ephemeral=True
        )


class ReviewCommentModal(discord.ui.Modal, title="코멘트 작성"):
    comment_input = discord.ui.TextInput(
        label="코멘트",
        placeholder="한줄 코멘트를 입력하세요",
        max_length=100,
        style=discord.TextStyle.short,
    )

    def __init__(self, review_id, message):
        super().__init__()
        self.review_id = review_id
        self.message = message

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        db = interaction.client.db
        content = self.comment_input.value.strip()
        if not content:
            await interaction.followup.send("❌ 코멘트 내용을 입력해주세요.", ephemeral=True)
            return

        comment_id = db.add_comment(
            self.review_id, interaction.user.id,
            interaction.user.display_name, content
        )
        if not comment_id:
            await interaction.followup.send("❌ 코멘트 저장에 실패했습니다.", ephemeral=True)
            return

        # Update button counts on the original message
        counts = db.get_reaction_counts(self.review_id)
        comment_count = db.get_comment_count(self.review_id)
        view = ReviewReactionView()
        view.update_counts(counts, comment_count)

        try:
            await self.message.edit(view=view)
        except Exception as e:
            print(f"[ERROR] ReviewCommentModal: Failed to update view: {e}")

        await interaction.followup.send(
            f"✅ 코멘트가 등록되었습니다: \"{content}\"", ephemeral=True
        )
