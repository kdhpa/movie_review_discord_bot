import discord
from database import Database

REACTION_TYPES = {
    'fire':     {'emoji': '\U0001f525', 'label': '존나 잘썼노', 'row': 0},
    'clap':     {'emoji': '\U0001f44f', 'label': '잘썼노', 'row': 0},
    'thumbsup': {'emoji': '\U0001f44d', 'label': '좋아요', 'row': 0},
    'laugh':    {'emoji': '\U0001f602', 'label': '재밌어요', 'row': 1},
    'hmm':      {'emoji': '\U0001f914', 'label': '뭐하냐?', 'row': 1},
    'skull':    {'emoji': '\U0001f480', 'label': '병신', 'row': 1},
}


def _make_reaction_button(rtype, info, count=0):
    """Create a reaction button with emoji + label, showing count if > 0."""
    label = info['label'] if count == 0 else f"{info['label']} : {count}"
    return discord.ui.Button(
        style=discord.ButtonStyle.secondary,
        label=label,
        emoji=info['emoji'],
        custom_id=f"review_reaction:{rtype}",
        row=info['row'],
    )


class ReviewReactionView(discord.ui.View):
    """Persistent view for review reactions and thread comments."""

    def __init__(self):
        super().__init__(timeout=None)
        self._build_buttons()

    def _build_buttons(self):
        # Reaction buttons (row 0 and 1)
        for rtype, info in REACTION_TYPES.items():
            btn = _make_reaction_button(rtype, info)
            btn.callback = self._make_reaction_callback(rtype)
            self.add_item(btn)

    def update_counts(self, reaction_counts):
        """Update button labels with counts."""
        for child in self.children:
            if not isinstance(child, discord.ui.Button) or not child.custom_id:
                continue

            if child.custom_id.startswith("review_reaction:"):
                rtype = child.custom_id.split(":")[1]
                info = REACTION_TYPES.get(rtype)
                if info:
                    count = reaction_counts.get(rtype, 0)
                    child.label = info['label'] if count == 0 else f"{info['label']} : {count}"

    def _make_reaction_callback(self, rtype):
        async def callback(interaction: discord.Interaction):
            db = interaction.client.db
            review = db.get_review_by_message_id(interaction.message.id)
            if not review:
                await interaction.response.send_message(
                    "❌ 이 메시지에 연결된 리뷰를 찾을 수 없습니다.", ephemeral=True
                )
                return

            # Get user's current reaction
            user_reaction = db.get_user_reaction(review['id'], interaction.user.id)

            # Show ephemeral status view with user's reaction highlighted
            status_view = ReactionStatusView(review, interaction.message, user_reaction)
            await interaction.response.send_message(
                f"🎬 **{review['movie_title']}** 리뷰 반응\n"
                f"내 반응: {REACTION_TYPES[user_reaction]['emoji'] + ' ' + REACTION_TYPES[user_reaction]['label'] if user_reaction else '없음'}",
                view=status_view,
                ephemeral=True
            )

        return callback


class ReactionStatusView(discord.ui.View):
    """Ephemeral view showing user's reaction status with selected reaction in blue."""

    def __init__(self, review, original_message, user_reaction):
        super().__init__(timeout=180)  # 3 minutes timeout for ephemeral
        self.review = review
        self.original_message = original_message
        self.user_reaction = user_reaction
        self._build_buttons()

    def _build_buttons(self):
        for rtype, info in REACTION_TYPES.items():
            # Use primary (blue) if this is user's current reaction, else secondary (gray)
            style = discord.ButtonStyle.primary if rtype == self.user_reaction else discord.ButtonStyle.secondary
            btn = discord.ui.Button(
                style=style,
                label=info['label'],
                emoji=info['emoji'],
                custom_id=f"status_reaction:{rtype}",
                row=info['row'],
            )
            btn.callback = self._make_status_callback(rtype)
            self.add_item(btn)

    def _make_status_callback(self, rtype):
        async def callback(interaction: discord.Interaction):
            info = REACTION_TYPES[rtype]
            modal = ReactionCommentModal(self.review, self.original_message, rtype, info)
            await interaction.response.send_modal(modal)

        return callback


class ReactionCommentModal(discord.ui.Modal):
    """Modal for reaction with optional comment."""

    comment_input = discord.ui.TextInput(
        label="코멘트",
        placeholder="(선택) 코멘트를 입력하세요",
        max_length=500,
        style=discord.TextStyle.paragraph,
        required=False,
    )

    def __init__(self, review, message, rtype, info):
        # Title: emoji + label (e.g., "🔥 존나 잘썼노")
        super().__init__(title=f"{info['emoji']} {info['label']}")
        self.review = review
        self.message = message
        self.rtype = rtype
        self.info = info

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        db = interaction.client.db

        # Toggle reaction
        action, _ = db.toggle_reaction(
            self.review['id'], interaction.user.id,
            interaction.user.display_name, self.rtype
        )
        if action is None:
            await interaction.followup.send(
                "❌ 반응 처리 중 오류가 발생했습니다.", ephemeral=True
            )
            return

        # Update button counts
        counts = db.get_reaction_counts(self.review['id'])
        view = ReviewReactionView()
        view.update_counts(counts)
        await self.message.edit(view=view)

        # Handle comment if provided
        comment = self.comment_input.value.strip()
        if comment:
            # Check if user already has a comment on this review
            is_edit = db.has_user_comment(self.review['id'], interaction.user.id)
            old_message_id = None
            if is_edit:
                # Get old message id before deleting
                old_message_id = db.get_user_comment_message_id(self.review['id'], interaction.user.id)
                # Delete old comment from DB
                db.delete_user_comment(self.review['id'], interaction.user.id)

            try:
                # Check if thread already exists
                thread = self.message.thread

                if thread is None:
                    # Create a new thread for discussion
                    thread_name = f"💬 {self.review['movie_title']} 토론"
                    if len(thread_name) > 100:
                        thread_name = thread_name[:97] + "..."

                    thread = await self.message.create_thread(
                        name=thread_name,
                        auto_archive_duration=1440,  # 24 hours
                    )

                    # Lock the thread so only bot can send messages via modal
                    await thread.edit(locked=True)

                    # Send initial message
                    await thread.send(
                        f"💬 **{self.review['movie_title']}** 리뷰 토론 쓰레드입니다.\n"
                        f"반응 버튼을 눌러 코멘트를 남겨주세요!"
                    )

                # Delete old thread message if editing
                if is_edit and old_message_id:
                    try:
                        old_msg = await thread.fetch_message(old_message_id)
                        await old_msg.delete()
                    except discord.NotFound:
                        pass  # Message already deleted
                    except Exception as e:
                        print(f"[WARN] Failed to delete old comment message: {e}")

                # Send the comment with reaction info
                sent_msg = await thread.send(
                    f"{self.info['emoji']} **{interaction.user.display_name}**: {comment}"
                )

                # Save comment to DB with thread_message_id
                db.add_comment(
                    self.review['id'], interaction.user.id,
                    interaction.user.display_name, comment, sent_msg.id
                )

                action_msg = "추가" if action == "added" else "취소"
                comment_msg = "수정" if is_edit else "등록"
                await interaction.followup.send(
                    f"✅ {self.info['emoji']} 반응이 {action_msg}되었고, 코멘트가 {comment_msg}되었습니다!\n"
                    f"👉 {thread.mention}",
                    ephemeral=True
                )

            except discord.Forbidden:
                action_msg = "추가" if action == "added" else "취소"
                await interaction.followup.send(
                    f"✅ {self.info['emoji']} 반응이 {action_msg}되었습니다.\n"
                    f"⚠️ 쓰레드 권한이 없어 코멘트는 등록되지 않았습니다.",
                    ephemeral=True
                )
            except Exception as e:
                print(f"[ERROR] ReactionCommentModal thread: {e}")
                action_msg = "추가" if action == "added" else "취소"
                await interaction.followup.send(
                    f"✅ {self.info['emoji']} 반응이 {action_msg}되었습니다.\n"
                    f"⚠️ 코멘트 등록 중 오류가 발생했습니다.",
                    ephemeral=True
                )
        else:
            # No comment, just reaction toggle
            action_msg = "추가" if action == "added" else "취소"
            await interaction.followup.send(
                f"✅ {self.info['emoji']} 반응이 {action_msg}되었습니다!",
                ephemeral=True
            )
