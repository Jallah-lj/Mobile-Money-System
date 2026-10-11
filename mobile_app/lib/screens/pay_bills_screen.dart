import 'package:flutter/material.dart';

import '../api_client.dart';

class PayBillsScreen extends StatefulWidget {
  const PayBillsScreen({super.key, required this.api});

  final ApiClient api;

  @override
  State<PayBillsScreen> createState() => _PayBillsScreenState();
}

class _PayBillsScreenState extends State<PayBillsScreen> {
  final _formKey = GlobalKey<FormState>();
  final _amountController = TextEditingController();

  List<dynamic> _billers = [];
  int? _selectedBillerId;
  bool _loadingCatalog = true;
  bool _paying = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadBillers();
  }

  @override
  void dispose() {
    _amountController.dispose();
    super.dispose();
  }

  Future<void> _loadBillers() async {
    try {
      final data = await widget.api.billers();
      if (mounted) {
        setState(() {
          _billers = List<dynamic>.from(data['billers'] as List<dynamic>);
          _loadingCatalog = false;
        });
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _loadingCatalog = false;
          _error = e.message;
        });
      }
    }
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_selectedBillerId == null) {
      setState(() => _error = 'Choose a biller');
      return;
    }
    final amount = double.tryParse(_amountController.text.trim());
    if (amount == null || amount <= 0) {
      setState(() => _error = 'Enter a valid amount');
      return;
    }
    setState(() {
      _paying = true;
      _error = null;
    });
    try {
      final result = await widget.api.payBill(_selectedBillerId!, amount);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(result['message']?.toString() ?? 'Paid')),
        );
        Navigator.of(context).pop();
      }
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _paying = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Pay bills')),
      body: SafeArea(
        child: _loadingCatalog
            ? const Center(child: CircularProgressIndicator())
            : Padding(
                padding: const EdgeInsets.all(24),
                child: Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (_billers.isEmpty)
                        const Text(
                            'No billers are registered yet. Ask an admin to add some.')
                      else ...[
                        DropdownButtonFormField<int>(
                          value: _selectedBillerId,
                          decoration: const InputDecoration(
                            labelText: 'Biller',
                            prefixIcon: Icon(Icons.receipt_long),
                          ),
                          items: _billers.map((b) {
                            final map = b as Map<String, dynamic>;
                            final name = map['name']?.toString() ?? '';
                            final category = map['category']?.toString() ?? '';
                            return DropdownMenuItem<int>(
                              value: map['id'] as int,
                              child: Text('$name ($category)'),
                            );
                          }).toList(),
                          onChanged: (v) =>
                              setState(() => _selectedBillerId = v),
                          validator: (v) => v == null ? 'Choose a biller' : null,
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          controller: _amountController,
                          keyboardType: const TextInputType.numberWithOptions(
                              decimal: true),
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
                        const SizedBox(height: 8),
                        const Text(
                          'A small flat fee may apply, shown in your balance after payment.',
                          style: TextStyle(fontSize: 12),
                        ),
                      ],
                      const SizedBox(height: 16),
                      if (_error != null)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: Text(_error!,
                              style: TextStyle(
                                  color: Theme.of(context).colorScheme.error)),
                        ),
                      FilledButton(
                        onPressed: (_paying || _billers.isEmpty) ? null : _submit,
                        child: _paying
                            ? const SizedBox(
                                height: 20,
                                width: 20,
                                child: CircularProgressIndicator(
                                    strokeWidth: 2, color: Colors.white),
                              )
                            : const Text('Pay bill'),
                      ),
                    ],
                  ),
                ),
              ),
      ),
    );
  }
}
