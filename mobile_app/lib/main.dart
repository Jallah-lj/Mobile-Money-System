import 'package:flutter/material.dart';

import 'api_client.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';

void main() {
  runApp(const MobileMoneyApp());
}

class MobileMoneyApp extends StatefulWidget {
  const MobileMoneyApp({super.key});

  @override
  State<MobileMoneyApp> createState() => _MobileMoneyAppState();
}

class _MobileMoneyAppState extends State<MobileMoneyApp> {
  final ApiClient api = ApiClient();
  bool _booting = true;
  bool _loggedIn = false;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    await api.restoreSession();
    var loggedIn = api.isLoggedIn;
    if (loggedIn) {
      try {
        await api.me(); // Validate the stored token.
      } on ApiException {
        loggedIn = false;
      }
    }
    if (mounted) {
      setState(() {
        _loggedIn = loggedIn;
        _booting = false;
      });
    }
  }

  void _onLoggedIn() => setState(() => _loggedIn = true);

  void _onLoggedOut() => setState(() => _loggedIn = false);

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Mobile Money',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: Colors.green,
        brightness: Brightness.light,
        useMaterial3: true,
      ),
      darkTheme: ThemeData(
        colorSchemeSeed: Colors.green,
        brightness: Brightness.dark,
        useMaterial3: true,
      ),
      home: _booting
          ? const Scaffold(body: Center(child: CircularProgressIndicator()))
          : _loggedIn
              ? HomeScreen(api: api, onLoggedOut: _onLoggedOut)
              : LoginScreen(api: api, onLoggedIn: _onLoggedIn),
    );
  }
}
