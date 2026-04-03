import datetime
import json

from flask import Blueprint, abort, jsonify, render_template, request, session

from CTFd.models import Teams, Users, db
from CTFd.plugins import (
    register_admin_plugin_menu_bar,
    register_plugin_script,
    register_user_page_menu_bar,
)
from CTFd.utils import get_config, set_config
from CTFd.utils.decorators import admins_only, authed_only
from CTFd.utils.user import get_current_user, is_admin

from .models import Ticket, TicketMessage, TicketNotification

DEFAULT_CATEGORIES = ["General", "Support", "Report", "Infraction", "Hint Request"]

tickets_bp = Blueprint(
    "tickets",
    __name__,
    template_folder="templates",
    static_folder="assets",
    static_url_path="/plugins/tickets/assets",
)


def get_categories():
    raw = get_config("tickets_categories")
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return DEFAULT_CATEGORIES


def get_limits():
    return {
        "user": int(get_config("tickets_limit_user") or 0),
        "team": int(get_config("tickets_limit_team") or 0),
    }


def check_ticket_limit(user, scope):
    limits = get_limits()
    if scope == "team" and limits["team"] > 0 and user.team_id:
        count = Ticket.query.filter_by(
            team_id=user.team_id, scope="team"
        ).filter(Ticket.status != "closed").count()
        if count >= limits["team"]:
            return f"Team ticket limit reached ({limits['team']} open tickets max)"
    if scope == "user" and limits["user"] > 0:
        count = Ticket.query.filter_by(
            author_id=user.id, scope="user"
        ).filter(Ticket.status != "closed").count()
        if count >= limits["user"]:
            return f"Ticket limit reached ({limits['user']} open tickets max)"
    return None


def notify_ticket(ticket, message_preview, is_reply=False):
    action = "New reply on" if is_reply else "New ticket"
    title = f"{action}: {ticket.title}"
    content = message_preview[:200]

    target_user_ids = set()

    if ticket.scope == "team" and ticket.team_id:
        team = Teams.query.get(ticket.team_id)
        if team:
            for member in team.members:
                target_user_ids.add(member.id)
    else:
        target_user_ids.add(ticket.author_id)

    current_user = get_current_user()
    if current_user:
        target_user_ids.discard(current_user.id)

    for uid in target_user_ids:
        notif = TicketNotification(
            user_id=uid,
            ticket_id=ticket.id,
            title=title,
            content=content,
        )
        db.session.add(notif)
    db.session.commit()


def serialize_ticket(ticket, include_messages=False):
    data = {
        "id": ticket.id,
        "title": ticket.title,
        "category": ticket.category,
        "status": ticket.status,
        "priority": ticket.priority,
        "scope": ticket.scope,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "author_id": ticket.author_id,
        "author_name": ticket.author.name if ticket.author else "Unknown",
        "team_id": ticket.team_id,
        "team_name": ticket.team.name if ticket.team else None,
    }
    if include_messages:
        data["messages"] = [serialize_message(m) for m in ticket.messages.all()]
    return data


def serialize_message(msg):
    return {
        "id": msg.id,
        "content": msg.content,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "author_id": msg.author_id,
        "author_name": msg.author.name if msg.author else "Unknown",
        "is_admin": msg.is_admin,
    }


# ── Targeted notification API ────────────────────────────────

@tickets_bp.route("/api/tickets/notifications", methods=["GET"])
@authed_only
def api_get_notifications():
    user = get_current_user()
    notifs = TicketNotification.query.filter_by(
        user_id=user.id, read=False
    ).order_by(TicketNotification.created_at.desc()).limit(20).all()
    return jsonify({"success": True, "data": [{
        "id": n.id,
        "ticket_id": n.ticket_id,
        "title": n.title,
        "content": n.content,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    } for n in notifs]})


@tickets_bp.route("/api/tickets/notifications/read", methods=["POST"])
@authed_only
def api_mark_notifications_read():
    user = get_current_user()
    data = request.get_json()
    ids = data.get("ids", [])
    if ids:
        TicketNotification.query.filter(
            TicketNotification.user_id == user.id,
            TicketNotification.id.in_(ids)
        ).update({TicketNotification.read: True}, synchronize_session=False)
    else:
        TicketNotification.query.filter_by(
            user_id=user.id, read=False
        ).update({TicketNotification.read: True}, synchronize_session=False)
    db.session.commit()
    return jsonify({"success": True})


# ── Search API (admin only) ──────────────────────────────────

@tickets_bp.route("/api/tickets/search/users", methods=["GET"])
@admins_only
def api_search_users():
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify({"success": True, "data": []})
    results = Users.query.filter(
        Users.banned == False,
        Users.hidden == False,
        (Users.name.ilike(f"%{q}%") | Users.email.ilike(f"%{q}%"))
    ).order_by(Users.name).limit(20).all()
    return jsonify({"success": True, "data": [
        {"id": u.id, "name": u.name, "email": u.email} for u in results
    ]})


@tickets_bp.route("/api/tickets/search/teams", methods=["GET"])
@admins_only
def api_search_teams():
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify({"success": True, "data": []})
    results = Teams.query.filter(
        Teams.name.ilike(f"%{q}%")
    ).order_by(Teams.name).limit(20).all()
    return jsonify({"success": True, "data": [
        {"id": t.id, "name": t.name, "member_count": len(t.members)} for t in results
    ]})


# ── Categories API ───────────────────────────────────────────

@tickets_bp.route("/api/tickets/categories", methods=["GET"])
@authed_only
def api_get_categories():
    return jsonify({"success": True, "data": get_categories()})


@tickets_bp.route("/api/tickets/categories", methods=["PUT"])
@admins_only
def api_set_categories():
    data = request.get_json()
    categories = data.get("categories", [])
    categories = [c.strip() for c in categories if c.strip()]
    if not categories:
        categories = DEFAULT_CATEGORIES
    set_config("tickets_categories", json.dumps(categories))
    return jsonify({"success": True, "data": categories})


@tickets_bp.route("/api/tickets/settings", methods=["GET"])
@admins_only
def api_get_settings():
    return jsonify({"success": True, "data": {
        "categories": get_categories(),
        "limits": get_limits(),
    }})


@tickets_bp.route("/api/tickets/settings", methods=["PUT"])
@admins_only
def api_set_settings():
    data = request.get_json()
    if "categories" in data:
        cats = [c.strip() for c in data["categories"] if c.strip()]
        set_config("tickets_categories", json.dumps(cats if cats else DEFAULT_CATEGORIES))
    if "limits" in data:
        lim = data["limits"]
        set_config("tickets_limit_user", str(max(0, int(lim.get("user", 0)))))
        set_config("tickets_limit_team", str(max(0, int(lim.get("team", 0)))))
    return jsonify({"success": True})


# ── Admin pages ──────────────────────────────────────────────

@tickets_bp.route("/admin/tickets")
@admins_only
def admin_tickets():
    tickets = Ticket.query.order_by(Ticket.updated_at.desc()).all()
    return render_template("tickets/admin_list.html", tickets=tickets)


@tickets_bp.route("/admin/tickets/settings")
@admins_only
def admin_tickets_settings():
    categories = get_categories()
    limits = get_limits()
    return render_template("tickets/admin_settings.html", categories=categories, limits=limits)


@tickets_bp.route("/admin/tickets/<int:ticket_id>")
@admins_only
def admin_ticket_view(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    return render_template("tickets/admin_view.html", ticket=ticket)


@tickets_bp.route("/admin/tickets/new")
@admins_only
def admin_ticket_new():
    categories = get_categories()
    return render_template("tickets/admin_new.html", categories=categories)


# ── User pages ───────────────────────────────────────────────

@tickets_bp.route("/tickets")
@authed_only
def user_tickets():
    user = get_current_user()
    conditions = [Ticket.author_id == user.id]
    if user.team_id:
        conditions.append((Ticket.scope == "team") & (Ticket.team_id == user.team_id))
    user_tickets = Ticket.query.filter(
        db.or_(*conditions)
    ).order_by(Ticket.updated_at.desc()).all()
    return render_template("tickets/user_list.html", tickets=user_tickets)


@tickets_bp.route("/tickets/<int:ticket_id>")
@authed_only
def user_ticket_view(ticket_id):
    user = get_current_user()
    ticket = Ticket.query.get_or_404(ticket_id)
    allowed = (ticket.author_id == user.id) or (ticket.scope == "team" and user.team_id and ticket.team_id == user.team_id)
    if not allowed and not is_admin():
        abort(403)
    return render_template("tickets/user_view.html", ticket=ticket)


@tickets_bp.route("/tickets/new")
@authed_only
def user_ticket_new():
    categories = get_categories()
    return render_template("tickets/user_new.html", categories=categories)


# ── API endpoints ────────────────────────────────────────────

@tickets_bp.route("/api/tickets", methods=["GET"])
@authed_only
def api_list_tickets():
    if is_admin():
        status_filter = request.args.get("status")
        scope_filter = request.args.get("scope")
        query = Ticket.query
        if status_filter:
            query = query.filter_by(status=status_filter)
        if scope_filter:
            query = query.filter_by(scope=scope_filter)
        tickets = query.order_by(Ticket.updated_at.desc()).all()
    else:
        user = get_current_user()
        conditions = [Ticket.author_id == user.id]
        if user.team_id:
            conditions.append((Ticket.scope == "team") & (Ticket.team_id == user.team_id))
        tickets = Ticket.query.filter(
            db.or_(*conditions)
        ).order_by(Ticket.updated_at.desc()).all()
    return jsonify({"success": True, "data": [serialize_ticket(t) for t in tickets]})


@tickets_bp.route("/api/tickets", methods=["POST"])
@authed_only
def api_create_ticket():
    data = request.get_json()
    user = get_current_user()

    title = data.get("title", "").strip()
    content = data.get("content", "").strip()
    category = data.get("category", "General")
    scope = data.get("scope", "user")
    priority = data.get("priority", "normal")
    target_user_id = data.get("target_user_id")
    target_team_id = data.get("target_team_id")

    if not title or not content:
        return jsonify({"success": False, "errors": ["Title and message are required"]}), 400

    if not is_admin():
        limit_err = check_ticket_limit(user, scope)
        if limit_err:
            return jsonify({"success": False, "errors": [limit_err]}), 429

    ticket = Ticket(
        title=title,
        category=category,
        scope=scope,
        priority=priority if is_admin() else "normal",
        author_id=user.id,
    )

    if is_admin():
        if target_user_id:
            target = Users.query.get(target_user_id)
            if not target:
                return jsonify({"success": False, "errors": ["User not found"]}), 404
            ticket.author_id = target_user_id
            ticket.scope = "user"
        if target_team_id:
            ticket.scope = "team"
            ticket.team_id = target_team_id
        elif scope == "team" and not target_team_id:
            if target_user_id:
                target = Users.query.get(target_user_id)
                if target and target.team_id:
                    ticket.team_id = target.team_id
    else:
        if scope == "team" and user.team_id:
            ticket.team_id = user.team_id
        elif scope == "team" and not user.team_id:
            ticket.scope = "user"

    db.session.add(ticket)
    db.session.flush()

    message = TicketMessage(
        ticket_id=ticket.id,
        author_id=user.id,
        content=content,
        is_admin=is_admin(),
    )
    db.session.add(message)
    db.session.commit()

    return jsonify({"success": True, "data": serialize_ticket(ticket, include_messages=True)})


@tickets_bp.route("/api/tickets/admin-create", methods=["POST"])
@admins_only
def api_admin_create_ticket():
    data = request.get_json()
    user = get_current_user()

    title = data.get("title", "").strip()
    content = data.get("content", "").strip()
    category = data.get("category", "General")
    priority = data.get("priority", "normal")
    scope = data.get("scope", "user")
    target_user_id = data.get("target_user_id")
    target_team_id = data.get("target_team_id")

    if not title or not content:
        return jsonify({"success": False, "errors": ["Title and message are required"]}), 400

    ticket = Ticket(
        title=title,
        category=category,
        priority=priority,
        scope=scope,
        author_id=user.id,
    )

    if scope == "team" and target_team_id:
        ticket.team_id = target_team_id
        ticket.scope = "team"
    elif scope == "user" and target_user_id:
        ticket.author_id = target_user_id
        ticket.scope = "user"

    db.session.add(ticket)
    db.session.flush()

    message = TicketMessage(
        ticket_id=ticket.id,
        author_id=user.id,
        content=content,
        is_admin=True,
    )
    db.session.add(message)
    db.session.commit()

    notify_ticket(ticket, content)

    return jsonify({"success": True, "data": serialize_ticket(ticket, include_messages=True)})


@tickets_bp.route("/api/tickets/<int:ticket_id>", methods=["GET"])
@authed_only
def api_get_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    user = get_current_user()
    if not is_admin():
        allowed = (ticket.author_id == user.id) or (ticket.scope == "team" and user.team_id and ticket.team_id == user.team_id)
        if not allowed:
            abort(403)
    return jsonify({"success": True, "data": serialize_ticket(ticket, include_messages=True)})


@tickets_bp.route("/api/tickets/<int:ticket_id>/messages", methods=["POST"])
@authed_only
def api_add_message(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    user = get_current_user()

    if not is_admin():
        allowed = (ticket.author_id == user.id) or (ticket.scope == "team" and user.team_id and ticket.team_id == user.team_id)
        if not allowed:
            abort(403)

    data = request.get_json()
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"success": False, "errors": ["Message content is required"]}), 400

    msg = TicketMessage(
        ticket_id=ticket.id,
        author_id=user.id,
        content=content,
        is_admin=is_admin(),
    )
    db.session.add(msg)
    ticket.updated_at = datetime.datetime.utcnow()
    db.session.commit()

    if is_admin():
        notify_ticket(ticket, content, is_reply=True)

    return jsonify({"success": True, "data": serialize_message(msg)})


@tickets_bp.route("/api/tickets/<int:ticket_id>/status", methods=["PATCH"])
@authed_only
def api_update_status(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    user = get_current_user()

    data = request.get_json()
    new_status = data.get("status")

    if new_status not in ("open", "in_progress", "closed"):
        return jsonify({"success": False, "errors": ["Invalid status"]}), 400

    if not is_admin():
        allowed = (ticket.author_id == user.id) or (ticket.scope == "team" and user.team_id and ticket.team_id == user.team_id)
        if not allowed:
            abort(403)
        if new_status == "in_progress":
            return jsonify({"success": False, "errors": ["Only admins can set in_progress"]}), 403

    ticket.status = new_status
    ticket.updated_at = datetime.datetime.utcnow()
    db.session.commit()

    return jsonify({"success": True, "data": serialize_ticket(ticket)})


@tickets_bp.route("/api/tickets/<int:ticket_id>", methods=["DELETE"])
@admins_only
def api_delete_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    TicketNotification.query.filter_by(ticket_id=ticket.id).delete()
    TicketMessage.query.filter_by(ticket_id=ticket.id).delete()
    db.session.delete(ticket)
    db.session.commit()
    return jsonify({"success": True})


def load(app):
    app.db.create_all()
    app.register_blueprint(tickets_bp)
    register_admin_plugin_menu_bar(title="Tickets", route="/admin/tickets")
    register_user_page_menu_bar(title="Tickets", route="tickets")
    register_plugin_script("/plugins/tickets/assets/ticket-notifier.js")
