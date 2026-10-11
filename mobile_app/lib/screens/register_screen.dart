import 'package:flutter/material.dart';

import '../api_client.dart';

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key, required this.api});

  final ApiClient api;

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _formKey = GlobalKey<FormState>();
  final _phoneController = TextEditingController();
  final _nameController = TextEditingController();
  final _pinController = TextEditingController();
  final _secQController = TextEditingController();
  final _secAController = TextEditingController();

  bool _loading = false;
  bool _acceptLegal = false;
  String? _error;
  String? _policyText;

  @override
  void dispose() {
    _phoneController.dispose();
    _nameController.dispose();
    _pinController.dispose();
    _secQController.dispose();
    _secAController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (!_acceptLegal) {
      setState(() => _error = 'You must accept the Terms of Service and the Privacy Policy.');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await widget.api.register(
        phone: _phoneController.text.trim(),
        name: _nameController.text.trim(),
        pin: _pinController.text.trim(),
        secQ: _secQController.text.trim(),
        secA: _secAController.text.trim(),
        acceptTerms: true,
        acceptPrivacy: true,
      );
      // Back to the login screen with the phone prefilled. If 2FA is enabled
      // (the platform default), logging in will continue at the OTP stage.
      if (mounted) {
        Navigator.of(context).pop(_phoneController.text.trim());
      }
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _showLegalDocuments() async {
    if (_policyText != null) return;
    try {
      final policy = await widget.api.legalDocument('privacy_policy');
      final terms = await widget.api.legalDocument('terms_of_service');
      if (mounted) {
        setState(() {
          _policyText =
              'PRIVACY POLICY v${policy['version']}\n\n${policy['content']}'
              '\n\nTERMS OF SERVICE v${terms['version']}\n\n${terms['content']}';
        });
        showDialog<void>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Terms & Privacy Policy'),
            content: SizedBox(
              width: double.maxFinite,
              child: SingleChildScrollView(child: Text(_policyText!)),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Close'),
              ),
            ],
          ),
        );
      }
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Create account')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
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
                  controller: _nameController,
                  decoration: const InputDecoration(
                    labelText: 'Full name',
                    prefixIcon: Icon(Icons.person),
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
                    labelText: 'PIN (4+ digits)',
                    prefixIcon: Icon(Icons.lock),
                  ),
                  validator: (v) => v == null || v.trim().length < 4
                      ? 'PIN must be at least 4 digits'
                      : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _secQController,
                  decoration: const InputDecoration(
                    labelText: 'Security question',
                    prefixIcon: Icon(Icons.help_outline),
                  ),
                  validator: (v) =>
                      v == null || v.trim().isEmpty ? 'Required' : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _secAController,
                  decoration: const InputDecoration(
                    labelText: 'Security answer',
                    prefixIcon: Icon(Icons.question_answer),
                  ),
                  validator: (v) =>
                      v == null || v.trim().isEmpty ? 'Required' : null,
                ),
                const SizedBox(height: 12),
                CheckboxListTile(
                  value: _acceptLegal,
                  onChanged: (v) => setState(() => _acceptLegal = v ?? false),
                  title: const Text(
                      'I accept the Terms of Service and the Privacy Policy'),
                  subtitle: TextButton(
                    onPressed: _showLegalDocuments,
                    child: const Text('Read them'),
                  ),
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                ),
                const SizedBox(height: 8),
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
                      : const Text('Register'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
