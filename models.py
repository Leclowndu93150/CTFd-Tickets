import datetime

from CTFd.models import db


class Ticket(db.Model):
    __tablename__ = "tickets"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(256), nullable=False)
    category = db.Column(db.String(64), default="general")
    status = db.Column(db.String(32), default="open")
    priority = db.Column(db.String(32), default="normal")
    scope = db.Column(db.String(32), default="user")
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True)

    author = db.relationship("Users", foreign_keys=[author_id], lazy="select")
    team = db.relationship("Teams", foreign_keys=[team_id], lazy="select")
    messages = db.relationship("TicketMessage", backref="ticket", lazy="dynamic", order_by="TicketMessage.created_at.asc()")

    def __init__(self, **kwargs):
        super(Ticket, self).__init__(**kwargs)


class TicketMessage(db.Model):
    __tablename__ = "ticket_messages"
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    author = db.relationship("Users", foreign_keys=[author_id], lazy="select")

    def __init__(self, **kwargs):
        super(TicketMessage, self).__init__(**kwargs)


class TicketNotification(db.Model):
    __tablename__ = "ticket_notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(256), nullable=False)
    content = db.Column(db.String(512), nullable=False)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    user = db.relationship("Users", foreign_keys=[user_id], lazy="select")
    ticket = db.relationship("Ticket", foreign_keys=[ticket_id], lazy="select")

    def __init__(self, **kwargs):
        super(TicketNotification, self).__init__(**kwargs)
