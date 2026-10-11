import 'package:flutter/material.dart';

import '../api_client.dart';
import 'history_screen.dart';
import 'pay_bills_screen.dart';
import 'send_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.api, required this.onLoggedOut});

  final ApiClient api;
  final VoidCallback onLoggedOut;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  Map<String, dynamic>? _me;
  List<dynamic> _recent = [];
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final me = await widget.api.me();
      final recent = await widget.api.history(limit: 5);
      if (mounted) {
        setState(() {
          _me = me;
          _recent = recent;
          _error = null;
        });
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _logout() async {
    await widget.api.logout();
    widget.onLoggedOut();
  }

  Future<void> _push(Widget screen) async {
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));
    _load();
  }

  double get _balance {
    final raw = _me?['balance'];
    return double.tryParse(raw?.toString() ?? '0') ?? 0;
  }

  String get _currency => _me?['currency']?.toString() ?? 'USD';

  bool get _kycVerified => _me?['is_verified'] == 1;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Home')),
      drawer: Drawer(
        child: ListView(
          children: [
            DrawerHeader(
              decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.primary),
              child: Align(
                alignment: Alignment.bottomLeft,
                child: Text(
                  _me?['name']?.toString() ?? '',
                  style: const TextStyle(color: Colors.white, fontSize: 20),
                ),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.send),
              title: const Text('Send money'),
              onTap: () {
                Navigator.of(context).pop();
                _push(SendScreen(api: widget.api));
              },
            ),
            ListTile(
              leading: const Icon(Icons.receipt_long),
              title: const Text('Pay bills'),
              onTap: () {
                Navigator.of(context).pop();
                _push(PayBillsScreen(api: widget.api));
              },
            ),
            ListTile(
              leading: const Icon(Icons.history),
              title: const Text('History'),
              onTap: () {
                Navigator.of(context).pop();
                _push(HistoryScreen(api: widget.api));
              },
            ),
            const Divider(),
            ListTile(
              leading: const Icon(Icons.logout),
              title: const Text('Log out'),
              onTap: _logout,
            ),
          ],
        ),
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  children: [
                    Text('Balance',
                        style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 8),
                    Text(
                      '$_currency ${_balance.toStringAsFixed(2)}',
                      style: Theme.of(context).textTheme.headlineLarge,
                    ),
                    const SizedBox(height: 8),
                    Chip(
                      label: Text(_kycVerified ? 'KYC verified' : 'KYC pending'),
                      avatar: Icon(
                        _kycVerified ? Icons.verified : Icons.pending,
                        size: 18,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: () => _push(SendScreen(api: widget.api)),
                    icon: const Icon(Icons.send),
                    label: const Text('Send'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: FilledButton.tonalIcon(
                    onPressed: () => _push(PayBillsScreen(api: widget.api)),
                    icon: const Icon(Icons.receipt_long),
                    label: const Text('Pay bills'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: FilledButton.tonalIcon(
                    onPressed: () => _push(HistoryScreen(api: widget.api)),
                    icon: const Icon(Icons.history),
                    label: const Text('History'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(_error!,
                    style: TextStyle(
                        color: Theme.of(context).colorScheme.error)),
              ),
            Text('Recent activity',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            if (_recent.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: Text('No transactions yet', textAlign: TextAlign.center),
              )
            else
              ..._recent.map((t) => _TransactionTile(
                    transaction: t as Map<String, dynamic>,
                    myPhone: _me?['phone']?.toString() ?? '',
                  )),
          ],
        ),
      ),
    );
  }
}

class _TransactionTile extends StatelessWidget {
  const _TransactionTile({required this.transaction, required this.myPhone});

  final Map<String, dynamic> transaction;
  final String myPhone;

  @override
  Widget build(BuildContext context) {
    final amount = double.tryParse(transaction['amount']?.toString() ?? '0') ?? 0;
    final incoming = transaction['receiver_phone']?.toString() == myPhone;
    final color = incoming ? Colors.green : Colors.red;
    final timestamp = transaction['timestamp']?.toString() ?? '';
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: color.withOpacity(0.15),
        child: Icon(incoming ? Icons.arrow_downward : Icons.arrow_upward,
            color: color),
      ),
      title: Text(transaction['description']?.toString().isNotEmpty == true
          ? transaction['description'].toString()
          : transaction['type']?.toString() ?? ''),
      subtitle: Text(
          '${transaction['type']} · $timestamp · ${transaction['status']}'),
      trailing: Text(
        '${incoming ? '+' : '-'}${amount.toStringAsFixed(2)}',
        style: TextStyle(color: color, fontWeight: FontWeight.bold),
      ),
    );
  }
}
