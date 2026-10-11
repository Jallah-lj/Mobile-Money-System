import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:uuid/uuid.dart';

/// Base URL of the Mobile Money REST API.
///
/// Defaults to the Android emulator's alias for the host machine. Override at
/// run time, e.g.:
///   flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000
const String apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

/// Error thrown for any non-2xx API response.
class ApiException implements Exception {
  ApiException(this.statusCode, this.message);

  final int statusCode;
  final String message;

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// Thin typed wrapper around the Mobile Money REST API.
///
/// The session token is kept in secure storage and sent as a Bearer token on
/// every authenticated call.
class ApiClient {
  ApiClient({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;
  final FlutterSecureStorage _storage = const FlutterSecureStorage();
  final Uuid _uuid = const Uuid();

  static const String _tokenKey = 'session_token';
  String? _token;

  bool get isLoggedIn => _token != null;

  /// Loads a previously saved session token (call once at app start).
  Future<void> restoreSession() async {
    _token = await _storage.read(key: _tokenKey);
  }

  Future<void> _saveToken(String token) async {
    _token = token;
    await _storage.write(key: _tokenKey, value: token);
  }

  Future<void> _clearToken() async {
    _token = null;
    await _storage.delete(key: _tokenKey);
  }

  /// A fresh key for the Idempotency-Key header (safe retries over flaky networks).
  String newIdempotencyKey() => _uuid.v4();

  Future<dynamic> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
    Map<String, String>? extraHeaders,
  }) async {
    final uri = Uri.parse('$apiBaseUrl$path');
    final headers = <String, String>{
      'Content-Type': 'application/json',
      if (_token != null) 'Authorization': 'Bearer $_token',
      ...?extraHeaders,
    };
    late final http.Response response;
    if (method == 'GET') {
      response = await _client.get(uri, headers: headers);
    } else if (method == 'POST') {
      response = await _client.post(uri, headers: headers, body: _encode(body));
    } else if (method == 'PATCH') {
      response = await _client.patch(uri, headers: headers, body: _encode(body));
    } else if (method == 'DELETE') {
      response = await _client.delete(uri, headers: headers);
    } else {
      throw ArgumentError('Unsupported HTTP method: $method');
    }
    if (response.statusCode >= 400) {
      var message = 'Request failed (${response.statusCode})';
      try {
        final decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic> && decoded['detail'] != null) {
          message = decoded['detail'].toString();
        }
      } on FormatException {
        // Keep the generic message.
      }
      if (response.statusCode == 401) {
        await _clearToken(); // Session revoked — force re-login.
      }
      throw ApiException(response.statusCode, message);
    }
    if (response.body.isEmpty) return null;
    return jsonDecode(response.body);
  }

  static String? _encode(Map<String, dynamic>? body) =>
      body == null ? null : jsonEncode(body);

  static Map<String, dynamic> _asMap(dynamic data) =>
      data as Map<String, dynamic>;

  static List<dynamic> _asList(dynamic data, String key) =>
      List<dynamic>.from(_asMap(data)[key] as List<dynamic>);

  // --- Auth -----------------------------------------------------------------

  Future<Map<String, dynamic>> register({
    required String phone,
    required String name,
    required String pin,
    required String secQ,
    required String secA,
    String currency = 'USD',
  }) async {
    return _asMap(await _request('POST', '/auth/register', body: {
      'phone': phone,
      'name': name,
      'pin': pin,
      'sec_q': secQ,
      'sec_a': secA,
      'currency': currency,
    }));
  }

  /// Returns either `{access_token, user}` or `{requires_otp: true}`.
  Future<Map<String, dynamic>> login(String phone, String pin) async {
    final data = _asMap(await _request('POST', '/auth/login', body: {
      'phone': phone,
      'pin': pin,
    }));
    final token = data['access_token'];
    if (token is String) {
      await _saveToken(token);
    }
    return data;
  }

  /// Completes a 2FA login; stores the session token.
  Future<Map<String, dynamic>> verifyOtp(String phone, String code) async {
    final data = _asMap(await _request('POST', '/auth/verify-otp', body: {
      'phone': phone,
      'code': code,
    }));
    final token = data['access_token'];
    if (token is String) {
      await _saveToken(token);
    }
    return data;
  }

  Future<void> logout() async {
    try {
      await _request('POST', '/auth/logout');
    } on ApiException {
      // Even if the server call fails, drop the local session.
    }
    await _clearToken();
  }

  /// Current user profile + balance.
  Future<Map<String, dynamic>> me() async =>
      _asMap(await _request('GET', '/auth/me'));

  // --- Wallet -----------------------------------------------------------------

  Future<Map<String, dynamic>> transfer(
    String receiverPhone,
    double amount, {
    String description = '',
    String? idempotencyKey,
  }) async {
    return _asMap(await _request('POST', '/me/transfer',
        body: {
          'receiver_phone': receiverPhone,
          'amount': amount,
          'description': description,
        },
        extraHeaders: idempotencyKey == null
            ? null
            : {'Idempotency-Key': idempotencyKey}));
  }

  Future<Map<String, dynamic>> requestMoney(
    String payerPhone,
    double amount, {
    String description = 'Money Request',
  }) async {
    return _asMap(await _request('POST', '/me/request', body: {
      'payer_phone': payerPhone,
      'amount': amount,
      'description': description,
    }));
  }

  Future<List<dynamic>> myRequests() async =>
      _asList(await _request('GET', '/me/requests'), 'requests');

  Future<Map<String, dynamic>> payRequest(String transactionId) async =>
      _asMap(await _request('POST', '/me/requests/$transactionId/pay'));

  Future<Map<String, dynamic>> declineRequest(String transactionId) async =>
      _asMap(await _request('POST', '/me/requests/$transactionId/decline'));

  Future<List<dynamic>> history({int limit = 50}) async =>
      _asList(await _request('GET', '/me/history?limit=$limit'), 'transactions');

  // --- Bills --------------------------------------------------------------------

  Future<Map<String, dynamic>> billers() async =>
      _asMap(await _request('GET', '/billers'));

  Future<Map<String, dynamic>> payBill(
    int billerId,
    double amount, {
    String description = 'Bill Payment',
  }) async {
    return _asMap(await _request('POST', '/me/pay-bill', body: {
      'biller_id': billerId,
      'amount': amount,
      'description': description,
    }));
  }

  // --- Beneficiaries --------------------------------------------------------------

  Future<List<dynamic>> beneficiaries() async =>
      _asList(await _request('GET', '/me/beneficiaries'), 'beneficiaries');

  Future<Map<String, dynamic>> addBeneficiary(
    String phone, {
    String nickname = '',
  }) async {
    return _asMap(await _request('POST', '/me/beneficiaries', body: {
      'phone': phone,
      'nickname': nickname,
    }));
  }

  Future<void> removeBeneficiary(String phone) async {
    await _request('DELETE', '/me/beneficiaries/${Uri.encodeComponent(phone)}');
  }

  Future<List<dynamic>> recentRecipients() async =>
      _asList(await _request('GET', '/me/recent-recipients'), 'recipients');

  // --- Scheduled payments -----------------------------------------------------------

  Future<List<dynamic>> scheduledPayments() async =>
      _asList(await _request('GET', '/me/scheduled'), 'scheduled');

  Future<Map<String, dynamic>> createScheduledPayment({
    required String type, // 'TRANSFER' or 'BILL_PAYMENT'
    required double amount,
    String description = '',
    String receiverPhone = '',
    int? billerId,
    String frequency = 'once',
  }) async {
    return _asMap(await _request('POST', '/me/scheduled', body: {
      'type': type,
      'amount': amount,
      'description': description,
      'receiver_phone': receiverPhone,
      'biller_id': billerId,
      'frequency': frequency,
    }));
  }

  Future<Map<String, dynamic>> cancelScheduledPayment(int id) async =>
      _asMap(await _request('POST', '/me/scheduled/$id/cancel'));

  Future<Map<String, dynamic>> setScheduledPaymentActive(
    int id,
    bool active,
  ) async {
    return _asMap(
        await _request('PATCH', '/me/scheduled/$id', body: {'active': active}));
  }

  // --- Support tickets ----------------------------------------------------------------

  Future<List<dynamic>> myTickets() async =>
      _asList(await _request('GET', '/me/tickets'), 'tickets');

  Future<Map<String, dynamic>> createTicket(
    String subject,
    String category,
    String message, {
    String priority = 'normal',
  }) async {
    return _asMap(await _request('POST', '/me/tickets', body: {
      'subject': subject,
      'category': category,
      'message': message,
      'priority': priority,
    }));
  }

  // --- Profile, KYC, privacy ------------------------------------------------------------

  Future<Map<String, dynamic>> submitKyc(String idType, String idNumber) async {
    return _asMap(await _request('POST', '/me/kyc', body: {
      'id_type': idType,
      'id_number': idNumber,
    }));
  }

  Future<Map<String, dynamic>> dataExport() async =>
      _asMap(await _request('GET', '/me/data-export'));
}
