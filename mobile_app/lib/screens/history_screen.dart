import 'package:flutter/material.dart';

import '../api_client.dart';

class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key, required this.api});

  final ApiClient api;

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  List<dynamic> _transactions = [];
  String _myPhone = '';
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final me = await widget.api.me();
      final transactions = await widget.api.history(limit: 100);
      if (mounted) {
        setState(() {
          _myPhone = me['phone']?.toString() ?? '';
          _transactions = transactions;
          _loading = false;
        });
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _error = e.message;
          _loading = false;
        });
      }
    }
  }

  String _formatTimestamp(String raw) {
    final parsed = DateTime.tryParse(raw);
    if (parsed == null) return raw;
    final local = parsed.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${local.year}-${two(local.month)}-${two(local.day)} '
        '${two(local.hour)}:${two(local.minute)}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('History')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? Center(child: Text(_error!))
                : _transactions.isEmpty
                    ? const Center(child: Text('No transactions yet'))
                    : ListView.builder(
                        itemCount: _transactions.length,
                        itemBuilder: (context, index) {
                          final t =
                              _transactions[index] as Map<String, dynamic>;
                          final amount =
                              double.tryParse(t['amount']?.toString() ?? '0') ??
                                  0;
                          final incoming =
                              t['receiver_phone']?.toString() == _myPhone;
                          final color = incoming ? Colors.green : Colors.red;
                          return ListTile(
                            leading: CircleAvatar(
                              backgroundColor: color.withOpacity(0.15),
                              child: Icon(
                                incoming
                                    ? Icons.arrow_downward
                                    : Icons.arrow_upward,
                                color: color,
                              ),
                            ),
                            title: Text(
                              (t['description']?.toString().isNotEmpty == true)
                                  ? t['description'].toString()
                                  : t['type']?.toString() ?? '',
                            ),
                            subtitle: Text(
                              '${t['type']} · ${_formatTimestamp(t['timestamp']?.toString() ?? '')} · ${t['status']}',
                            ),
                            trailing: Text(
                              '${incoming ? '+' : '-'}${amount.toStringAsFixed(2)}',
                              style: TextStyle(
                                  color: color, fontWeight: FontWeight.bold),
                            ),
                          );
                        },
                      ),
      ),
    );
  }
}
