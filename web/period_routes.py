# -*- coding: utf-8 -*-
"""endpointهای مدیریت دوره‌ها — فقط ادمین."""
from flask import jsonify, session, request
import web.auth as auth
import web.periods as periods


def register(app):

    @app.route("/api/periods", methods=["GET"])
    @auth.login_required
    def api_periods_list():
        return jsonify({
            "opened": periods.list_opened(),
            "months": periods.PERSIAN_MONTHS,
        })

    @app.route("/api/periods/available")
    @auth.login_required
    def api_periods_available():
        """لیست ماه‌های مجاز برای کاربر جاری."""
        role = session.get("role", "user")

        if role == "admin":
            years = ["1404", "1405", "1406", "1407"]
            months = periods.PERSIAN_MONTHS
            all_periods = [f"{y}-{m}" for y in years for m in months]
            return jsonify({
                "all": True,
                "periods": all_periods,
                "years": years,
                "months": months,
            })
        else:
            opened = periods.list_opened()
            opened_list = [x["period_month"] for x in opened]
            years_set = set()
            months_set = set()
            for pm in opened_list:
                if "-" in pm:
                    y, m = pm.split("-", 1)
                    years_set.add(y)
                    months_set.add(m)
            return jsonify({
                "all": False,
                "periods": opened_list,
                "years": sorted(years_set, reverse=True),
                "months": [m for m in periods.PERSIAN_MONTHS if m in months_set],
            })

    @app.route("/api/periods/toggle", methods=["POST"])
    @auth.admin_required
    def api_periods_toggle():
        data = request.get_json() or {}
        period_month = (data.get("period_month") or "").strip()
        note = (data.get("note") or "").strip()
        try:
            action = periods.toggle_period(
                period_month,
                user_id=session.get("user_id"),
                note=note,
            )
            return jsonify({"ok": True, "action": action, "period": period_month})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/periods/open", methods=["POST"])
    @auth.admin_required
    def api_periods_open():
        data = request.get_json() or {}
        period_month = (data.get("period_month") or "").strip()
        note = (data.get("note") or "").strip()
        try:
            periods.open_period(
                period_month,
                user_id=session.get("user_id"),
                note=note,
            )
            return jsonify({"ok": True, "period": period_month, "action": "opened"})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/periods/close", methods=["POST"])
    @auth.admin_required
    def api_periods_close():
        data = request.get_json() or {}
        period_month = (data.get("period_month") or "").strip()
        try:
            periods.close_period(period_month)
            return jsonify({"ok": True, "period": period_month, "action": "closed"})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/periods/is-open")
    @auth.login_required
    def api_periods_is_open():
        period = request.args.get("period", "").strip()
        return jsonify({"period": period, "is_open": periods.is_period_open(period)})