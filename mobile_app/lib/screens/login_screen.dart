import 'package:flutter/material.dart';

import '../api_client.dart';
import 'register_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.api, required this.onLoggedIn});

  final ApiClient api;
  final VoidCallback onLoggedIn;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _phoneController = TextEditingController();
  final _pinController = TextEditingController();
  final _otpController = TextEditingController();

  bool _loading = false;
  bool _otpStage = false;
  String? _error;

  @override
  void dispose() {
    _phoneController.dispose();
    _pinController.dispose();
    _otpController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      if (_otpStage) {
        await widget.api.verifyOtp(
          _phoneController.text.trim(),
          _otpController.text.trim(),
        );
        widget.onLoggedIn();
        return;
      }
      final result = await widget.api.login(
        _phoneController.text.trim(),
        _pinController.text.trim(),
      );
      if (result['requires_otp'] == true) {
        // 2FA accounts continue at the OTP stage (code sent by SMS).
        setState(() => _otpStage = true);
      } else {
        widget.onLoggedIn();
      }
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Mobile Money')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Icon(Icons.account_balance_wallet,
                    size: 72, color: Colors.green),
                const SizedBox(height: 16),
                Text(
                  _otpStage ? 'Enter your security code' : 'Welcome back',
                  style: Theme.of(context).textTheme.headlineSmall,
                  textAlign: TextAlign.center,
                ),
                if (_otpStage) ...[
                  const SizedBox(height: 8),
                  Text(
                    'A 6-digit code was sent to ${_phoneController.text.trim()}',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                ],
                const SizedBox(height: 24),
                if (!_otpStage) ...[
                  TextFormField(
                    controller: _phoneController,
                    keyboardType: TextInputType.phone,
                    decoration: const InputDecoration(
                      labelText: 'Phone number',
                      hintText: '+231776462520',
                      prefixIcon: Icon(Icons.phone),
                    ),
                    validator: (v) =>
                        v == null || v.trim().isEmpty ? 'Required' : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _pinController,
                    obscureText: true,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'PIN',
                      prefixIcon: Icon(Icons.lock),
                    ),
                    validator: (v) => v == null || v.trim().length < 4
                        ? 'PIN must be at least 4 digits'
                        : null,
                  ),
                ] else ...[
                  TextFormField(
                    controller: _otpController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: '6-digit code',
                      prefixIcon: Icon(Icons.sms),
                    ),
                    validator: (v) => v == null || v.trim().length != 6
                        ? 'Enter the 6-digit code'
                        : null,
                  ),
                ],
                const SizedBox(height: 16),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      _error!,
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error),
                    ),
                  ),
                FilledButton(
                  onPressed: _loading ? null : _submit,
                  child: _loading
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white),
                        )
                      : Text(_otpStage ? 'Verify' : 'Log in'),
                ),
                const SizedBox(height: 12),
                if (!_otpStage)
                  TextButton(
                    onPressed: () async {
                      final phone = await Navigator.of(context).push<String>(
                        MaterialPageRoute(
                          builder: (_) => RegisterScreen(api: widget.api),
                        ),
                      );
                      if (phone != null && mounted) {
                        _phoneController.text = phone;
                      }
                    },
                    child: const Text('No account? Register'),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
