from flask import Flask, request, jsonify, Response, render_template

import config
import modules
import utils.driver as driver
import utils.runner as runner

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/modules")
def api_modules():
    mods = []
    for m in modules.get_modules():
        mods.append({
            "name": m.name,
            "description": m.description,
            "icon": m.icon,
            "status": m.status,
        })
    return jsonify(mods)


@app.route("/api/run/<module_name>", methods=["POST"])
def api_run(module_name):
    mod = modules.get_module(module_name)
    if mod is None:
        return jsonify({"error": "模块不存在"}), 404
    if mod.status == "running":
        return jsonify({"error": "模块正在运行中"}), 409
    run_id = runner.start_module(mod)
    return jsonify({"run_id": run_id})


@app.route("/api/stop/<module_name>", methods=["POST"])
def api_stop(module_name):
    ok = runner.stop_module(module_name)
    return jsonify({"stopped": ok})


@app.route("/api/logs/<run_id>")
def api_logs(run_id):
    log_stream = runner.get_log_stream(run_id)
    if log_stream is None:
        return jsonify({"error": "run_id 不存在"}), 404
    return Response(
        log_stream.to_sse(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/device")
def api_device():
    try:
        d = driver.get_driver()
        # Appium-Python-Client 2.11 的 WebDriver 没有 is_connected()，
        # 与 utils/driver.py 的探活方式保持一致，用 page_source 判断 session。
        d.page_source
        status = True
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})
    return jsonify({"connected": status})


if __name__ == "__main__":
    print("JD Automation Platform starting...")
    print("Web UI: http://{}:{}".format(config.FLASK_HOST, config.FLASK_PORT))
    print("Appium: {}".format(config.APPIUM_HOST))
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
        threaded=True,
    )
