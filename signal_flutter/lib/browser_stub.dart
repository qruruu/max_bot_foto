import 'package:flutter/widgets.dart';
import 'browser.dart';
import 'models.dart';

SignalBrowser createBrowser() => MemoryBrowser();

/// Native implementation for widget tests. Production currently targets web.
class MemoryBrowser implements SignalBrowser {
  AppealDraft? draft;
  List<LocalPhoto> pickedPhotos = [];
  String? copied;
  @override
  Uri get location => Uri.parse('http://localhost/');
  @override
  bool get online => true;
  @override
  Future<AppealDraft?> loadDraft() async => draft;
  @override
  Future<void> saveDraft(AppealDraft value) async {
    draft = value;
  }

  @override
  Future<List<LocalPhoto>> pickPhotos(int remaining) async =>
      pickedPhotos.take(remaining).toList();
  @override
  Future<void> copy(String value) async {
    copied = value;
  }

  @override
  void setDirty(bool value) {}
  @override
  void reload() {}
  @override
  void listen({
    required void Function(bool) connectivity,
    required VoidCallback activity,
  }) {}
  @override
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
  }) => const ColoredBox(
    color: Color(0xffe6ede6),
    child: Center(child: Text('Карта территории')),
  );
  @override
  Widget photoDropTarget({
    required Widget child,
    required int remaining,
    required bool enabled,
    required VoidCallback onStart,
    required Future<void> Function(List<LocalPhoto>) onPhotos,
    required ValueChanged<String> onError,
  }) => child;
  @override
  void dispose() {}
}
