# web/master_routes.py — endpointهای Master Control
from flask import jsonify, session, request
import web.master_control as mc
import web.auth as auth


def register(app):

    @app.route("/master-control")
    @auth.admin_required
    def master_control_page():
        from flask import render_template
        return render_template("master_control.html")
    @app.route("/api/master/status")
    @auth.login_required
    def api_master_status():
        st = mc.get_status()
        st["is_owner"] = bool(session.get('master_verified', False))
        return jsonify(st)

    @app.route("/api/master/setup", methods=["POST"])
    @auth.login_required
    def api_master_setup():
        """ساخت فایل کلید — فقط بار اول"""
        if session.get('role') != 'admin':
            return jsonify({"error": "فقط مدیر"}), 403
        if mc.get_master_key_path().exists():
            return jsonify({"error": "فایل کلید از قبل وجود دارد"}), 400
        p = mc.create_master_key()
        return jsonify({"ok": True, "path": str(p)})

    @app.route("/api/master/activate", methods=["POST"])
    @auth.login_required
    def api_master_activate():
        """فعال‌سازی حالت مالک با رمز مخفی"""
        data = request.get_json() or {}
        pw = (data.get("password") or "").strip()
        if pw != mc.MASTER_PASSWORD:
            return jsonify({"error": "رمز مالک اشتباه است"}), 403
        ok, msg = mc.verify_master_key()
        if not ok:
            return jsonify({"error": msg}), 403
        session['master_verified'] = True
        return jsonify({"ok": True})

    @app.route("/api/master/deactivate", methods=["POST"])
    @auth.login_required
    def api_master_deactivate():
        session.pop('master_verified', None)
        return jsonify({"ok": True})

    @app.route("/api/master/lockdown", methods=["POST"])
    @auth.login_required
    def api_master_lockdown():
        """قفل اضطراری کل سامانه"""
        data = request.get_json() or {}
        pw = (data.get("password") or "").strip()
        if pw != mc.MASTER_PASSWORD:
            return jsonify({"error": "رمز اشتباه"}), 403
        ok, msg = mc.verify_master_key()
        if not ok:
            return jsonify({"error": msg}), 403
        state = bool(data.get("state", True))
        mc.set_lockdown(state)
        return jsonify({"ok": True, "lockdown": state})