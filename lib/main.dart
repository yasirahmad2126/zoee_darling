import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

const String serverBase = "http://127.0.0.1:5002";

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(MyAppWrapper());
}

class MyAppWrapper extends StatefulWidget {
  @override
  State<MyAppWrapper> createState() => _MyAppWrapperState();
}

class _MyAppWrapperState extends State<MyAppWrapper> {
  ThemeMode _themeMode = ThemeMode.light;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Chrome Profile Manager',
      debugShowCheckedModeBanner: false,
      themeMode: _themeMode,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.blueAccent,
          brightness: Brightness.light,
        ),
        useMaterial3: true,
      ),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.deepPurpleAccent,
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: ScaffoldMessenger(
        child: MyApp(
          onThemeChanged: (mode) => setState(() => _themeMode = mode),
          currentMode: _themeMode,
        ),
      ),
    );
  }
}

class ApiClient {
  String? token;
  final client = http.Client();

  Map<String, String> headers() {
    final h = {"Content-Type": "application/json"};
    if (token != null) h["X-Auth-Token"] = token!;
    return h;
  }

  Future<void> login(String password) async {
    final uri = Uri.parse("$serverBase/auth/login");
    final r = await client.post(
      uri,
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"password": password}),
    );
    if (r.statusCode != 200) throw Exception("HTTP ${r.statusCode}");
    final j = jsonDecode(r.body);
    if (j['ok'] == true)
      token = j['token'];
    else
      throw Exception(j['error'] ?? "Invalid password");
  }

  Future<List<dynamic>> getProfiles() async {
    final uri = Uri.parse("$serverBase/profiles");
    final r = await client.get(uri, headers: headers());
    if (r.statusCode != 200) throw Exception("HTTP ${r.statusCode}");
    final j = jsonDecode(r.body);
    if (j['ok'] == true) return j['profiles'];
    throw Exception(j['error'] ?? "Failed");
  }

  Future<void> launchProfile(String profile, String? email) async {
    final r = await client.post(
      Uri.parse("$serverBase/launch"),
      headers: headers(),
      body: jsonEncode({"profile": profile, "email": email}),
    );
    final j = jsonDecode(r.body);
    if (j['ok'] != true) throw Exception(j['error'] ?? "Launch failed");
  }

  Future<void> launchAll() async {
    final r = await client.post(
      Uri.parse("$serverBase/launch_all"),
      headers: headers(),
    );
    final j = jsonDecode(r.body);
    if (j['ok'] != true) throw Exception(j['error'] ?? "Launch all failed");
  }

  Future<void> startRefresh() async {
    final r = await client.post(
      Uri.parse("$serverBase/start_refresh"),
      headers: headers(),
    );
    final j = jsonDecode(r.body);
    if (j['ok'] != true) throw Exception(j['error'] ?? "Start refresh failed");
  }

  Future<void> stopRefresh() async {
    final r = await client.post(
      Uri.parse("$serverBase/stop_refresh"),
      headers: headers(),
    );
    final j = jsonDecode(r.body);
    if (j['ok'] != true) throw Exception(j['error'] ?? "Stop refresh failed");
  }

  Future<void> addProxies() async {
    final r = await client.post(
      Uri.parse("$serverBase/add_proxies"),
      headers: headers(),
    );
    final j = jsonDecode(r.body);
    if (j['ok'] != true) throw Exception(j['error'] ?? "Add proxies failed");
  }

  Future<void> changePassword(String newPassword) async {
    final r = await client.post(
      Uri.parse("$serverBase/change_password"),
      headers: headers(),
      body: jsonEncode({"new_password": newPassword}),
    );
    final j = jsonDecode(r.body);
    if (j['ok'] != true)
      throw Exception(j['error'] ?? "Change password failed");
  }

  Future<List<String>> getLogs() async {
    final r = await client.get(
      Uri.parse("$serverBase/logs"),
      headers: headers(),
    );
    if (r.statusCode != 200) throw Exception("HTTP ${r.statusCode}");
    final j = jsonDecode(r.body);
    if (j['ok'] == true) return List<String>.from(j['logs']);
    throw Exception(j['error'] ?? "Failed logs");
  }

  Future<void> closeAll() async {
    final r = await client.post(
      Uri.parse("$serverBase/close_all"),
      headers: headers(),
    );
    final j = jsonDecode(r.body);
    if (j['ok'] != true) throw Exception(j['error'] ?? "Close all failed");
  }

  // 🆕 SAFE REFRESH
  Future<void> safeRefresh() async {
    final r = await client.post(
      Uri.parse("$serverBase/safe_refresh"),
      headers: headers(),
    );
    final j = jsonDecode(r.body);
    if (j['ok'] != true) throw Exception(j['error'] ?? "Safe refresh failed");
  }

  // 🆕 QUARANTINE
  Future<List<String>> getQuarantine() async {
    final r = await client.get(
      Uri.parse("$serverBase/quarantine/list"),
      headers: headers(),
    );
    final j = jsonDecode(r.body);
    if (j['ok'] == true) return List<String>.from(j['quarantined']);
    throw Exception(j['error'] ?? "Failed to get quarantine list");
  }

  Future<void> resetQuarantine() async {
    final r = await client.post(
      Uri.parse("$serverBase/quarantine/reset"),
      headers: headers(),
    );
    final j = jsonDecode(r.body);
    if (j['ok'] != true)
      throw Exception(j['error'] ?? "Reset quarantine failed");
  }
}

class MyApp extends StatefulWidget {
  final Function(ThemeMode) onThemeChanged;
  final ThemeMode currentMode;

  MyApp({required this.onThemeChanged, required this.currentMode});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  final ApiClient api = ApiClient();
  List<dynamic> profiles = [];
  List<String> logs = [];
  Map<String, dynamic>? summary;
  Timer? logsTimer;
  Timer? summaryTimer;
  bool loggedIn = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _promptLogin());
  }

  @override
  void dispose() {
    logsTimer?.cancel();
    summaryTimer?.cancel();
    super.dispose();
  }

  Future<void> _promptLogin() async {
    final pw = await showDialog<String>(
      context: context,
      builder: (c) {
        String val = "";
        return AlertDialog(
          title: Text("Enter startup password"),
          content: TextField(obscureText: true, onChanged: (s) => val = s),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(c).pop(null),
              child: Text("Cancel"),
            ),
            ElevatedButton(
              onPressed: () => Navigator.of(c).pop(val),
              child: Text("Login"),
            ),
          ],
        );
      },
    );

    if (pw == null) return;

    try {
      await api.login(pw);
      setState(() => loggedIn = true);
      _loadProfiles();
      _startLogsPolling();
      _startSummaryPolling();
      _loadSummary();
      _showSnack("Logged in successfully");
    } catch (e) {
      _showSnack("Login failed: $e");
    }
  }

  Future<void> _loadProfiles() async {
    try {
      final p = await api.getProfiles();
      setState(() => profiles = p);
    } catch (e) {
      _showSnack("Failed to load profiles: $e");
    }
  }

  Future<void> _loadLogs() async {
    try {
      final l = await api.getLogs();
      setState(() => logs = l.reversed.take(400).toList());
    } catch (_) {}
  }

  Future<void> _loadSummary() async {
    try {
      final r = await api.client.get(
        Uri.parse("$serverBase/dashboard/summary"),
        headers: api.headers(),
      );
      if (r.statusCode == 200) {
        final j = jsonDecode(r.body);
        if (j['ok'] == true) {
          setState(() => summary = j['summary']);
        }
      }
    } catch (e) {
      print("Summary fetch failed: $e");
    }
  }

  void _startLogsPolling() {
    logsTimer?.cancel();
    logsTimer = Timer.periodic(Duration(seconds: 6), (_) => _loadLogs());
  }

  void _startSummaryPolling() {
    summaryTimer?.cancel();
    summaryTimer = Timer.periodic(Duration(seconds: 10), (_) => _loadSummary());
  }

  void _showSnack(String txt) {
    if (mounted)
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(txt)));
  }

  Future<void> _showQuarantineDialog() async {
    try {
      final q = await api.getQuarantine();
      showDialog(
        context: context,
        builder:
            (c) => AlertDialog(
              title: Text("Quarantined Profiles"),
              content:
                  q.isEmpty
                      ? Text("No profiles are currently quarantined.")
                      : SizedBox(
                        width: 300,
                        height: 200,
                        child: ListView(
                          children: q.map((p) => Text(p)).toList(),
                        ),
                      ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(c),
                  child: Text("Close"),
                ),
              ],
            ),
      );
    } catch (e) {
      _showSnack("Failed to load quarantine list: $e");
    }
  }

  Widget _summaryItem(IconData icon, String title, String value) {
    return Column(
      children: [
        Icon(icon, size: 28, color: Theme.of(context).colorScheme.primary),
        SizedBox(height: 6),
        Text(title, style: TextStyle(fontWeight: FontWeight.bold)),
        SizedBox(height: 4),
        Text(value, style: TextStyle(fontSize: 16)),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text("Chrome Profile Manager"),
        actions: [
          Row(
            children: [
              Radio<ThemeMode>(
                value: ThemeMode.light,
                groupValue: widget.currentMode,
                onChanged: (val) => widget.onThemeChanged(ThemeMode.light),
              ),
              Icon(Icons.light_mode),
              Radio<ThemeMode>(
                value: ThemeMode.dark,
                groupValue: widget.currentMode,
                onChanged: (val) => widget.onThemeChanged(ThemeMode.dark),
              ),
              Icon(Icons.dark_mode),
              IconButton(
                icon: Icon(Icons.refresh),
                onPressed: loggedIn ? _loadProfiles : null,
              ),
            ],
          ),
        ],
      ),
      body: Padding(
        padding: EdgeInsets.all(12),
        child: Column(
          children: [
            if (summary != null)
              Card(
                elevation: 3,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Padding(
                  padding: EdgeInsets.all(12),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                    children: [
                      _summaryItem(
                        Icons.people,
                        "Profiles",
                        summary!['total_profiles'].toString(),
                      ),
                      _summaryItem(
                        Icons.play_circle,
                        "Active",
                        summary!['active_profiles'].toString(),
                      ),
                      _summaryItem(
                        Icons.shield,
                        "Quarantined",
                        summary!['quarantined'].toString(),
                      ),
                      _summaryItem(
                        Icons.refresh,
                        "Status",
                        summary!['refresh_status'] ?? "Idle",
                      ),
                      _summaryItem(
                        Icons.timer,
                        "Range",
                        summary!['refresh_range'] ?? "-",
                      ),
                    ],
                  ),
                ),
              ),
            SizedBox(height: 12),
            // existing control buttons and layout continue here ↓↓↓
            // Main Control Buttons Row
            Row(
              children: [
                ElevatedButton(
                  onPressed:
                      loggedIn
                          ? () async {
                            await api.launchAll();
                            _showSnack("Launched all");
                            _loadLogs();
                          }
                          : null,
                  child: Text("Launch All"),
                ),
                SizedBox(width: 8),
                ElevatedButton(
                  onPressed:
                      loggedIn
                          ? () async {
                            await api.startRefresh();
                            _showSnack("Started refresh");
                            _loadLogs();
                          }
                          : null,
                  child: Text("Start Refresh"),
                ),
                SizedBox(width: 8),
                ElevatedButton(
                  onPressed:
                      loggedIn
                          ? () async {
                            await api.stopRefresh();
                            _showSnack("Stopped refresh");
                            _loadLogs();
                          }
                          : null,
                  child: Text("Stop Refresh"),
                ),
                SizedBox(width: 8),
                ElevatedButton(
                  onPressed:
                      loggedIn
                          ? () async {
                            await api.safeRefresh();
                            _showSnack("Safe Refresh cycle started");
                            _loadLogs();
                          }
                          : null,
                  child: Text("Safe Refresh"),
                ),
              ],
            ),

            SizedBox(height: 8),

            Row(
              children: [
                ElevatedButton(
                  onPressed: loggedIn ? _showQuarantineDialog : null,
                  child: Text("View Quarantine"),
                ),
                SizedBox(width: 8),
                ElevatedButton(
                  onPressed:
                      loggedIn
                          ? () async {
                            await api.resetQuarantine();
                            _showSnack("Quarantine reset");
                            _loadLogs();
                          }
                          : null,
                  child: Text("Reset Quarantine"),
                ),
                SizedBox(width: 8),
                ElevatedButton(
                  onPressed:
                      loggedIn
                          ? () async {
                            await api.addProxies();
                            _showSnack("Proxies applied");
                            _loadLogs();
                          }
                          : null,
                  child: Text("Add Proxies"),
                ),
              ],
            ),

            SizedBox(height: 12),

            // Main layout with profiles and logs
            Expanded(
              child: Row(
                children: [
                  // Profiles
                  Expanded(
                    flex: 2,
                    child: Card(
                      elevation: 2,
                      child: Padding(
                        padding: EdgeInsets.all(8),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              "Profiles",
                              style: TextStyle(fontWeight: FontWeight.bold),
                            ),
                            SizedBox(height: 8),
                            Expanded(
                              child:
                                  profiles.isEmpty
                                      ? Center(
                                        child: Text(
                                          "No profiles or not loaded",
                                        ),
                                      )
                                      : ListView.builder(
                                        itemCount: profiles.length,
                                        itemBuilder: (c, i) {
                                          final p = profiles[i];
                                          return ListTile(
                                            title: Text(p['profile']),
                                            subtitle: Text(p['email'] ?? ''),
                                            trailing: ElevatedButton(
                                              onPressed:
                                                  loggedIn
                                                      ? () async {
                                                        await api.launchProfile(
                                                          p['profile'],
                                                          p['email'],
                                                        );
                                                        _showSnack(
                                                          "Launched ${p['profile']}",
                                                        );
                                                        _loadLogs();
                                                      }
                                                      : null,
                                              child: Text("Launch"),
                                            ),
                                          );
                                        },
                                      ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),

                  SizedBox(width: 12),

                  // Logs
                  Expanded(
                    flex: 1,
                    child: Card(
                      elevation: 2,
                      child: Padding(
                        padding: EdgeInsets.all(8),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              "Activity Log",
                              style: TextStyle(fontWeight: FontWeight.bold),
                            ),
                            SizedBox(height: 8),
                            Expanded(
                              child:
                                  logs.isEmpty
                                      ? Center(child: Text("No logs"))
                                      : ListView(
                                        children:
                                            logs
                                                .map(
                                                  (l) => Text(
                                                    l,
                                                    style: TextStyle(
                                                      fontSize: 12,
                                                    ),
                                                  ),
                                                )
                                                .toList(),
                                      ),
                            ),
                            SizedBox(height: 12),
                            Row(
                              children: [
                                ElevatedButton(
                                  onPressed:
                                      loggedIn
                                          ? () async {
                                            await _changePasswordDialog();
                                            _loadLogs();
                                          }
                                          : null,
                                  child: Text("Change Password"),
                                ),
                                SizedBox(width: 8),
                                ElevatedButton(
                                  onPressed:
                                      loggedIn
                                          ? () async {
                                            await api.closeAll();
                                            _showSnack(
                                              "Closed all Chrome profiles",
                                            );
                                            _loadLogs();
                                            _loadProfiles();
                                          }
                                          : null,
                                  child: Text("Close All"),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _changePasswordDialog() async {
    final newPw = await showDialog<String>(
      context: context,
      builder: (c) {
        String val = "";
        return AlertDialog(
          title: Text("Set new password"),
          content: TextField(
            obscureText: true,
            onChanged: (s) => val = s,
            autofocus: true,
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(c).pop(null),
              child: Text("Cancel"),
            ),
            ElevatedButton(
              onPressed: () => Navigator.of(c).pop(val),
              child: Text("Set"),
            ),
          ],
        );
      },
    );
    if (newPw == null || newPw.trim().isEmpty) return;
    try {
      await api.changePassword(newPw.trim());
      _showSnack("Password changed");
    } catch (e) {
      _showSnack("Change password failed: $e");
    }
  }
}
