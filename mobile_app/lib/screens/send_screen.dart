import 'package:flutter/material.dart';

import '../api_client.dart';

class SendScreen extends StatefulWidget {
  const SendScreen({super.key, required this.api});

  final ApiClient api;

  @override
  State<SendScreen> createState() => _SendScreenState();
}

class _SendScreenState extends State<SendScreen> {
  final _formKey = GlobalKey<FormState>();
  final _receiverController = TextEditingController();
  final _amountController = TextEditingController();
  final _descriptionController = TextEditingController();

  List<dynamic> _beneficiaries = [];
  List<dynamic> _recent = [];
  bool _saveBeneficiary = false;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadContacts();
  }

  @override
  void dispose() {
    _receiverController.dispose();
    _amountController.dispose();
    _descriptionController.dispose();
    super.dispose();
  }

  Future<void> _loadContacts() async {
    try {
      final beneficiaries = await widget.api.beneficiaries();
      final recent = await widget.api.recentRecipients();
      if (mounted) {
        setState(() {
          _beneficiaries = beneficiaries;
          _recent = recent;
        });
      }
    } on ApiException {
      // Contacts are a convenience — the form works without them.
    }
  }

  Future<void> _pickContact() async {
    await showModalBottomSheet<void>(
      context: context,
      builder: (context) {
        return SafeArea(
          child: ListView(
            shrinkWrap: true,
            children: [
              const Padding(
                padding: EdgeInsets.all(16),
                child: Text('Saved beneficiaries',
                    style: TextStyle(fontWeight: FontWeight.bold)),
              ),
              ..._beneficiaries.map((b) {
                final map = b as Map<String, dynamic>;
                final phone = map['phone']?.toString() ?? '';
                final nickname = map['nickname']?.toString() ?? '';
                return ListTile(
                  leading: const Icon(Icons.person),
                  title: Text(nickname.isNotEmpty ? nickname : phone),
                  subtitle: Text(phone),
                  onTap: () {
                    _receiverController.text = phone;
                    Navigator.of(context).pop();
                  },
                );
              }),
              if (_beneficiaries.isEmpty)
                const ListTile(title: Text('No saved beneficiaries yet')),
              const Divider(),
              const Padding(
                padding: EdgeInsets.all(16),
                child: Text('Recent recipients',
                    style: TextStyle(fontWeight: FontWeight.bold)),
              ),
              ..._recent.map((phone) {
                final p = phone.toString();
                return ListTile(
                  leading: const Icon(Icons.history),
                  title: Text(p),
                  onTap: () {
                    _receiverController.text = p;
                    Navigator.of(context).pop();
                  },
                );
              }),
              if (_recent.isEmpty)
                const ListTile(title: Text('No recent recipients yet')),
            ],
          ),
        );
      },
    );
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    final amount = double.tryParse(_amountController.text.trim());
    if (amount == null || amount <= 0) {
      setState(() => _error = 'Enter a valid amount');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      // A fresh Idempotency-Key makes retries safe on flaky networks.
      final result = await widget.api.transfer(
        _receiverController.text.trim(),
        amount,
        description: _descriptionController.text.trim(),
        idempotencyKey: widget.api.newIdempotencyKey(),
      );
      if (_saveBeneficiary) {
        try {
          await widget.api.addBeneficiary(_receiverController.text.trim());
        } on ApiException {
          // Saving the beneficiary is best-effort.
        }
      }
      if (mounted) {
        await showDialog<void>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Transfer sent'),
            content: Text(result['message']?.toString() ?? 'Success'),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('OK'),
              ),
            ],
          ),
        );
        if (mounted) Navigator.of(context).pop();
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
      appBar: AppBar(title: const Text('Send money')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextFormField(
                  controller: _receiverController,
                  keyboardType: TextInputType.phone,
                  decoration: InputDecoration(
                    labelText: 'Recipient phone',
                    hintText: '+231776462520',
                    prefixIcon: const Icon(Icons.phone),
                    suffixIcon: IconButton(
                      icon: const Icon(Icons.contacts),
                      onPressed: _pickContact,
                      tooltip: 'Pick a contact',
                    ),
                  ),
                  validator: (v) =>
                      v == null || v.trim().isEmpty ? 'Required' : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _amountController,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(
                    labelText: 'Amount',
                    prefixIcon: Icon(Icons.attach_money),
                  ),
                  validator: (v) {
                    final value = double.tryParse(v?.trim() ?? '');
                    if (value == null || value <= 0) {
                      return 'Enter a valid amount';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _descriptionController,
                  decoration: const InputDecoration(
                    labelText: 'Description (optional)',
                    prefixIcon: Icon(Icons.notes),
                  ),
                ),
                const SizedBox(height: 8),
                CheckboxListTile(
                  value: _saveBeneficiary,
                  onChanged: (v) =>
                      setState(() => _saveBeneficiary = v ?? false),
                  title: const Text('Save recipient as beneficiary'),
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                ),
                const SizedBox(height: 8),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(_error!,
                        style: TextStyle(
                            color: Theme.of(context).colorScheme.error)),
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
                      : const Text('Send'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
