"""Serveur API factice pour le scénario http_callout (cible des Named
Credentials de credentials.yaml).

Lance un serveur Flask sur le port 5555 avec quelques endpoints simples.

Usage:
    python scenarios/http_callout/api_server.py   # puis run_scenario.py scenarios/http_callout
"""

from flask import Flask, request, jsonify

app = Flask(__name__)

# Stockage en mémoire pour les tests
_store = {}


@app.route("/api/accounts", methods=["GET"])
def list_accounts():
    """Retourne la liste des comptes stockés."""
    return jsonify(list(_store.values()))


@app.route("/api/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    """Retourne un compte par ID."""
    acc = _store.get(account_id)
    if acc is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(acc)


@app.route("/api/accounts", methods=["POST"])
def create_account():
    """Crée un compte et retourne l'ID généré."""
    data = request.get_json(force=True)
    account_id = "EXT-{:04d}".format(len(_store) + 1)
    data["id"] = account_id
    _store[account_id] = data
    return jsonify(data), 201


@app.route("/api/accounts/<account_id>", methods=["PUT"])
def update_account(account_id):
    """Met à jour un compte existant."""
    if account_id not in _store:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(force=True)
    data["id"] = account_id
    _store[account_id] = data
    return jsonify(data)


@app.route("/api/echo", methods=["POST"])
def echo():
    """Echo — retourne le body et les headers reçus."""
    return jsonify({
        "body": request.get_json(force=True, silent=True),
        "headers": dict(request.headers),
        "method": request.method,
    })


@app.route("/api/status", methods=["GET"])
def status():
    """Health check."""
    return jsonify({"status": "ok", "store_size": len(_store)})


@app.route("/api/reset", methods=["POST"])
def reset():
    """Vide le store (pour les tests)."""
    _store.clear()
    return jsonify({"status": "reset"})


if __name__ == "__main__":
    print("Test API server running on http://localhost:5555")
    app.run(port=5555, debug=False)
