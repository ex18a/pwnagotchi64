import logging
import json
import threading
import tomlkit
import pwnagotchi
from pwnagotchi import restart, plugins
from flask import abort
from flask import render_template_string

INDEX = """
{% extends "base.html" %}
{% set active_page = "plugins" %}
{% block title %}
    Webcfg
{% endblock %}

{% block meta %}
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, user-scalable=0" />
{% endblock %}{% block styles %}
{{ super() }}
<style>
    .webcfg-header {
        margin-bottom: 2rem;
        padding: 1.5rem 0;
        border-bottom: 1px solid var(--border-color);
    }

    #divTop {
        position: -webkit-sticky;
        position: sticky;
        top: 0;
        display: flex;
        gap: 0.5rem;
        align-items: center;
        width: 100%;
        padding: 1rem;
        margin-bottom: 1.5rem;
        font-size: 0.95rem;
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        z-index: 100;
    }

    #searchText {
        flex: 1;
        min-width: 200px;
    }

    #selAddType {
        min-width: 120px;
        cursor: pointer;
    }

    #divTop > span {
        display: flex;
        align-items: center;
    }

    .table-container {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        overflow: hidden;
        box-shadow: var(--shadow-md);
        margin-bottom: 2rem;
    }

    table {
        table-layout: auto;
        width: 100%;
        border-collapse: collapse;
        background-color: var(--card-bg);
    }

    thead {
        background-color: var(--card-bg);
    }

    th {
        padding: 14px 16px;
        text-align: left;
        color: var(--accent);
        font-weight: 600;
        font-family: var(--font-pixel);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-size: 0.85rem;
        border-bottom: 2px solid var(--border-color);
    }

    td {
        padding: 12px 16px;
        text-align: left;
        border-bottom: 1px solid var(--border-color);
        color: var(--text-body);
        font-size: 0.9rem;
    }

    tbody tr:hover {
        background-color: rgba(var(--accent-r), var(--accent-g), var(--accent-b), 0.05);
    }

    tbody tr.dirty {
        background-color: rgba(var(--accent-r), var(--accent-g), var(--accent-b), 0.12);
    }

    tbody tr:last-child td {
        border-bottom: none;
    }

    td:nth-child(1) {
        width: 50px;
        padding: 12px 8px;
        text-align: center;
    }

    td:nth-child(1) .del_btn_wrapper {
        display: flex;
        justify-content: center;
    }

    .remove {
        background-color: var(--danger);
        color: transparent;
        border: none;
        padding: 6px 6px;
        border-radius: 4px;
        cursor: pointer;
        min-width: 32px;
        min-height: 32px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='3 6 5 6 21 6'%3E%3C/polyline%3E%3Cpath d='M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'%3E%3C/path%3E%3Cline x1='10' y1='11' x2='10' y2='17'%3E%3C/line%3E%3Cline x1='14' y1='11' x2='14' y2='17'%3E%3C/line%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: center;
        background-size: 18px;
    }

    .remove:hover {
        background-color: var(--danger-hover);
    }

    #divSaveTop {
        position: -webkit-sticky;
        position: sticky;
        bottom: 0;
        display: flex;
        gap: 1rem;
        padding: 1rem;
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        flex-wrap: wrap;
        z-index: 100;
        margin-top: 2rem;
    }

    #divSaveTop .btn {
        flex: 1;
        min-width: 150px;
    }

    #divSaveTop p {
        width: 100%;
        margin: 0 0 0.5rem 0;
        font-size: 0.85rem;
        color: var(--text-body);
    }
</style>
{% endblock %}

{% block content %}
    <div class="webcfg-header">
        <h2>Configuration Manager</h2>
        <p>Only fields you actually change are written to config.toml -- everything else is left exactly as it was.</p>
    </div>

    <div id="divTop">
        <input type="text" id="searchText" placeholder="Search for options ..." title="Type an option name">
        <span><select id="selAddType"><option value="text">Text</option><option value="number">Number</option><option value="bool">Bool</option></select></span>
        <span><button class="btn primary" type="button" onclick="addOption()">+</button></span>
    </div>

    <div class="table-container" id="content"></div>

    <div id="divSaveTop">
        <p id="dirtyCount">No changes yet</p>
        <button class="btn primary" type="button" onclick="saveConfig()">Save and restart</button>
        <button class="btn danger" type="button" onclick="saveConfigNoRestart()">Save without restarting</button>
    </div>
{% endblock %}

{% block script %}
        var baseline = {};
        var deletedKeys = [];

        function updateDirtyCount() {
            var table = document.getElementById("tableOptions");
            var count = 0;
            if (table) {
                var rows = table.getElementsByTagName("tr");
                for (var i = 0; i < rows.length; i++) {
                    if (rows[i].dataset && rows[i].dataset.dirty == "1") count++;
                }
            }
            count += deletedKeys.length;
            document.getElementById("dirtyCount").textContent =
                count == 0 ? "No changes yet" : (count + " change(s) pending");
        }

        function markDirty(tr, input) {
            var orig = tr.dataset.orig;
            var cur = String(input.value);
            if (tr.dataset.existed == "1" && orig === cur) {
                tr.dataset.dirty = "0";
                tr.classList.remove("dirty");
            } else {
                tr.dataset.dirty = "1";
                tr.classList.add("dirty");
            }
            updateDirtyCount();
        }

        function addOption() {
          var input, table, tr, td, divDelBtn, btnDel, selType, selTypeVal;
          input = document.getElementById("searchText");
          var inputVal = input.value;
          if (!inputVal) return;
          selType = document.getElementById("selAddType");
          selTypeVal = selType.options[selType.selectedIndex].value;
          table = document.getElementById("tableOptions");
          if (table) {
            tr = table.insertRow();
            tr.dataset.existed = "0";
            tr.dataset.dirty = "1";
            tr.classList.add("dirty");

            divDelBtn = document.createElement("div");
            divDelBtn.className = "del_btn_wrapper";
            td = document.createElement("td");
            td.setAttribute("data-label", "");
            btnDel = document.createElement("Button");
            btnDel.onclick = function(){ delRow(this); };
            btnDel.className = "remove";
            divDelBtn.appendChild(btnDel);
            td.appendChild(divDelBtn);
            tr.appendChild(td);

            td = document.createElement("td");
            td.setAttribute("data-label", "Option");
            td.textContent = inputVal;
            tr.appendChild(td);

            td = document.createElement("td");
            td.setAttribute("data-label", "Value");
            if (selTypeVal == "bool") {
                input = document.createElement("select");
                var t = document.createElement("option"); t.value = "true"; t.text = "True";
                var f = document.createElement("option"); f.value = "false"; f.text = "False";
                input.appendChild(t); input.appendChild(f);
                input.onchange = function(){ markDirty(tr, input); };
            } else {
                input = document.createElement("input");
                input.type = selTypeVal;
                input.value = "";
                input.oninput = function(){ markDirty(tr, input); };
            }
            td.appendChild(input);
            tr.appendChild(td);

            input.value = "";
            updateDirtyCount();
          }
        }

        function collectChanges() {
            var table = document.getElementById("tableOptions");
            var changes = {};
            if (table) {
                var rows = table.getElementsByTagName("tr");
                for (var i = 0; i < rows.length; i++) {
                    var tr = rows[i];
                    if (!tr.dataset || tr.dataset.dirty != "1") continue;
                    var td = tr.getElementsByTagName("td");
                    if (td.length != 3) continue;
                    var key = td[1].textContent || td[1].innerText;
                    var input = td[2].getElementsByTagName("input");
                    var select = td[2].getElementsByTagName("select");
                    if (input.length > 0) {
                        var val = input[0].value;
                        if (input[0].type == "number") {
                            changes[key] = Number(val);
                        } else if (val.startsWith("[") && val.endsWith("]")) {
                            try { changes[key] = JSON.parse(val); } catch(e) { changes[key] = val; }
                        } else {
                            changes[key] = val;
                        }
                    } else if (select.length > 0) {
                        changes[key] = select[0].value === "true";
                    }
                }
            }
            return changes;
        }

        function doSave(restartAfter) {
            var payload = {
                changes: collectChanges(),
                deletes: deletedKeys,
                restart: restartAfter
            };
            if (Object.keys(payload.changes).length == 0 && payload.deletes.length == 0) {
                alert("No changes to save");
                return;
            }
            sendJSON("webcfg/save-config", payload, function(response) {
                if (response) {
                    if (response.status == "200") {
                        alert("Config updated" + (restartAfter ? ", restarting ..." : ""));
                        deletedKeys = [];
                        var table = document.getElementById("tableOptions");
                        if (table) {
                            var rows = table.getElementsByTagName("tr");
                            for (var i = 0; i < rows.length; i++) {
                                rows[i].dataset.dirty = "0";
                                rows[i].dataset.existed = "1";
                                rows[i].classList.remove("dirty");
                                var td = rows[i].getElementsByTagName("td");
                                if (td.length == 3) {
                                    var input = td[2].getElementsByTagName("input");
                                    if (input.length > 0) rows[i].dataset.orig = String(input[0].value);
                                }
                            }
                        }
                        updateDirtyCount();
                    } else {
                        alert("Error while updating the config (err-code: " + response.status + ")");
                    }
                }
            });
        }

        function saveConfig(){ doSave(true); }
        function saveConfigNoRestart(){ doSave(false); }

        var searchInput = document.getElementById("searchText");
        searchInput.onkeyup = function() {
            var filter, table, tr, td, i, txtValue;
            filter = searchInput.value.toUpperCase();
            table = document.getElementById("tableOptions");
            if (table) {
                tr = table.getElementsByTagName("tr");
                for (i = 0; i < tr.length; i++) {
                    td = tr[i].getElementsByTagName("td")[1];
                    if (td) {
                        txtValue = td.textContent || td.innerText;
                        tr[i].style.display = (txtValue.toUpperCase().indexOf(filter) > -1) ? "" : "none";
                    }
                }
            }
        }

        function sendJSON(url, data, callback) {
          var xobj = new XMLHttpRequest();
          var csrf = "{{ csrf_token() }}";
          xobj.open('POST', url);
          xobj.setRequestHeader("Content-Type", "application/json");
          xobj.setRequestHeader('x-csrf-token', csrf);
          xobj.onreadystatechange = function () {
                if (xobj.readyState == 4) { callback(xobj); }
          };
          xobj.send(JSON.stringify(data));
        }

        function loadJSON(url, callback) {
          var xobj = new XMLHttpRequest();
          xobj.overrideMimeType("application/json");
          xobj.open('GET', url, true);
          xobj.onreadystatechange = function () {
                if (xobj.readyState == 4 && xobj.status == "200") {
                  callback(JSON.parse(xobj.responseText));
                }
          };
          xobj.send(null);
        }

        function flattenJson(data) {
            var result = {};
            function recurse(cur, prop) {
                if (Array.isArray(cur) || Object(cur) !== cur) {
                    result[prop] = cur;
                    return;
                }
                var isEmpty = true;
                for (var p in cur) {
                    isEmpty = false;
                    recurse(cur[p], prop ? prop + "." + p : p);
                }
                if (isEmpty) result[prop] = {};
            }
            recurse(data, "");
            return result;
        }

        function delRow(btn) {
            var tr = btn.parentNode.parentNode.parentNode;
            if (tr.dataset.existed == "1") {
                var td = tr.getElementsByTagName("td");
                var key = td[1].textContent || td[1].innerText;
                deletedKeys.push(key);
            }
            tr.parentNode.removeChild(tr);
            updateDirtyCount();
        }

        function jsonToTable(json) {
            var table = document.createElement("table");
            table.id = "tableOptions";

            var tr = table.insertRow();
            var thDel = document.createElement("th"); thDel.innerHTML = "";
            var thOpt = document.createElement("th"); thOpt.innerHTML = "Option";
            var thVal = document.createElement("th"); thVal.innerHTML = "Value";
            tr.appendChild(thDel); tr.appendChild(thOpt); tr.appendChild(thVal);

            var td, divDelBtn, btnDel, input;
            Object.keys(json).sort().forEach(function(key) {
                tr = table.insertRow();
                tr.dataset.existed = "1";
                tr.dataset.dirty = "0";

                divDelBtn = document.createElement("div");
                divDelBtn.className = "del_btn_wrapper";
                td = document.createElement("td");
                td.setAttribute("data-label", "");
                btnDel = document.createElement("Button");
                btnDel.onclick = function(){ delRow(this); };
                btnDel.className = "remove";
                divDelBtn.appendChild(btnDel);
                td.appendChild(divDelBtn);
                tr.appendChild(td);

                td = document.createElement("td");
                td.setAttribute("data-label", "Option");
                td.textContent = key;
                tr.appendChild(td);

                td = document.createElement("td");
                td.setAttribute("data-label", "Value");
                var value = json[key];
                if (typeof(value) === 'boolean') {
                    input = document.createElement("select");
                    var t = document.createElement("option"); t.value = "true"; t.text = "True";
                    var f = document.createElement("option"); f.value = "false"; f.text = "False";
                    input.appendChild(t); input.appendChild(f);
                    input.value = String(value);
                    input.onchange = function(){ markDirty(tr, input); };
                } else {
                    input = document.createElement("input");
                    if (Array.isArray(value)) {
                        input.type = "text";
                        input.value = JSON.stringify(value);
                    } else {
                        var valType = typeof(value);
                        input.type = (valType === 'number') ? 'number' : 'text';
                        input.value = value;
                    }
                    input.oninput = function(){ markDirty(tr, input); };
                }
                tr.dataset.orig = String(input.value);
                td.appendChild(input);
                tr.appendChild(td);
            });

            return table;
        }

        loadJSON("webcfg/get-config", function(response) {
            baseline = flattenJson(response);
            var table = jsonToTable(baseline);
            var divContent = document.getElementById("content");
            divContent.innerHTML = "";
            divContent.appendChild(table);
        });
{% endblock %}
"""


class WebConfig(plugins.Plugin):
    __author__ = 'ex18a'
    __version__ = '1.0.0'
    __license__ = 'GPL3'
    __description__ = 'Edit config.toml from the web UI. Only the fields actually changed get written -- everything else in the file is left untouched.'

    def __init__(self):
        self.ready = False
        self.mode = 'AUTO'
        self._agent = None

    def on_config_changed(self, config):
        self.config = config
        self.ready = True

    def on_ready(self, agent):
        self._agent = agent
        self.mode = 'MANU' if agent.mode == 'manual' else 'AUTO'

    def on_internet_available(self, agent):
        self._agent = agent
        self.mode = 'MANU' if agent.mode == 'manual' else 'AUTO'

    def on_loaded(self):
        logging.info("webcfg: plugin loaded.")

    @staticmethod
    def _set_dotted(doc, dotted_key, value):
        parts = dotted_key.split('.')
        node = doc
        for part in parts[:-1]:
            if part in node and isinstance(node[part], dict):
                node = node[part]
            else:
                node = None
                break
        if node is not None and parts[-1] in node:
            node[parts[-1]] = value
        else:
            doc.append(tomlkit.key(parts), tomlkit.item(value))

    @staticmethod
    def _delete_dotted(doc, dotted_key):
        parts = dotted_key.split('.')
        chain = []
        node = doc
        for part in parts[:-1]:
            if part not in node:
                return
            chain.append((node, part))
            node = node[part]
        last_key = parts[-1]
        if last_key not in node:
            return
        del node[last_key]
        for container, key in reversed(chain):
            if key in container and len(container[key]) == 0:
                del container[key]
            else:
                break

    @staticmethod
    def _set_dict_dotted(d, dotted_key, value):
        parts = dotted_key.split('.')
        node = d
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value

    @staticmethod
    def _delete_dict_dotted(d, dotted_key):
        parts = dotted_key.split('.')
        node = d
        for part in parts[:-1]:
            if part not in node:
                return
            node = node[part]
        node.pop(parts[-1], None)

    def on_webhook(self, path, request):
        if not self.ready:
            return "Plugin not ready"

        if request.method == "GET":
            if path == "/" or not path:
                return render_template_string(INDEX)
            elif path == "get-config":
                return json.dumps(self.config)
            abort(404)

        elif request.method == "POST":
            if path != "save-config":
                abort(404)

            try:
                body = request.get_json()
                changes = body.get('changes', {})
                deletes = body.get('deletes', [])
                do_restart = bool(body.get('restart', False))

                config_path = '/etc/pwnagotchi/config.toml'
                with open(config_path, 'r') as fp:
                    doc = tomlkit.parse(fp.read())

                for key, value in changes.items():
                    self._set_dotted(doc, key, value)
                for key in deletes:
                    self._delete_dotted(doc, key)

                with open(config_path, 'w') as fp:
                    fp.write(tomlkit.dumps(doc))

                for key, value in changes.items():
                    self._set_dict_dotted(pwnagotchi.config, key, value)
                    if self._agent:
                        self._set_dict_dotted(self._agent._config, key, value)
                for key in deletes:
                    self._delete_dict_dotted(pwnagotchi.config, key)
                    if self._agent:
                        self._delete_dict_dotted(self._agent._config, key)

                if do_restart:
                    threading.Thread(target=restart, args=(self.mode,),
                                      kwargs={'restart_bettercap': False}, daemon=True).start()

                return "success"
            except Exception as ex:
                logging.error("[webcfg] %s", ex)
                return "config error", 500

        abort(404)
