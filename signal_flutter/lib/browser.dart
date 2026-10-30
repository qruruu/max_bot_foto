import 'package:flutter/widgets.dart';
import 'models.dart';
import 'browser_stub.dart'
    if (dart.library.js_interop) 'browser_web.dart'
    as implementation;

abstract class SignalBrowser {
  Uri get location;
  bool get online;
  Future<AppealDraft?> loadDraft();
  Future<void> saveDraft(AppealDraft draft);
  Future<List<LocalPhoto>> pickPhotos(int remaining);
  Future<void> copy(String value);
  void setDirty(bool value);
  void reload();
  void listen({
    required void Function(bool) connectivity,
    required VoidCallback activity,
  });
  Widget map({
    required String apiKey,
    required List<Organization> organizations,
    String organizationId = '',
    bool overview = false,
    bool preview = false,
    int? districtId,
    double? longitude,
    double? latitude,
    void Function(double longitude, double latitude)? onPoint,
    ValueChanged<String>? onOrganization,
  });
  Widget photoDropTarget({
    required Widget child,
    required int remaining,
    required bool enabled,
    required VoidCallback onStart,
    required Future<void> Function(List<LocalPhoto>) onPhotos,
    required ValueChanged<String> onError,
  });
  void dispose();
}

SignalBrowser createBrowser() => implementation.createBrowser();
