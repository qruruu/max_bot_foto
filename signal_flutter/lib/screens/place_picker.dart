import 'package:flutter/material.dart';
import '../controller.dart';
import '../theme.dart';

/// A separate route keeps HTML maps out of the scrolling form and its shell.
Future<void> pickAppealPlace(
  BuildContext context,
  SignalController controller,
) async {
  if (controller.locked) return;
  if (controller.address == null) {
    controller.backStep();
    return;
  }
  FocusScope.of(context).unfocus();
  final confirmed = await Navigator.of(context).push<bool>(
    MaterialPageRoute(
      fullscreenDialog: true,
      builder: (_) => PlacePickerScreen(controller: controller),
    ),
  );
  if (!context.mounted) return;
  if (confirmed == true) {
    controller.nextStep();
  } else {
    controller.backStep();
  }
}

class PlacePickerScreen extends StatefulWidget {
  const PlacePickerScreen({super.key, required this.controller});
  final SignalController controller;

  @override
  State<PlacePickerScreen> createState() => _PlacePickerScreenState();
}

class _PlacePickerScreenState extends State<PlacePickerScreen> {
  double? _longitude, _latitude;
  String? _error;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    final form = widget.controller.form;
    if (form.located &&
        widget.controller.allowsPoint(form.longitude!, form.latitude!)) {
      _longitude = form.longitude;
      _latitude = form.latitude;
    }
  }

  void _select(double longitude, double latitude) {
    setState(() {
      if (widget.controller.allowsPoint(longitude, latitude)) {
        _longitude = longitude;
        _latitude = latitude;
        _error = null;
      } else {
        _error = 'Выберите место внутри выделенной территории организации.';
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    final located = _longitude != null && _latitude != null;
    return Scaffold(
      key: const ValueKey('place-picker-screen'),
      backgroundColor: surface,
      appBar: AppBar(
        backgroundColor: surface,
        leading: IconButton(
          tooltip: 'Назад к территории',
          icon: const Icon(Icons.arrow_back, color: green),
          onPressed: () => Navigator.pop(context),
        ),
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Укажите место проблемы',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
            ),
            Text(
              c.form.address,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 12, color: muted),
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: c.browser.map(
              apiKey: c.catalog?.mapKey ?? '',
              organizations: c.organizations,
              organizationId: c.form.organizationId,
              districtId: c.address!['district_id'] as int,
              longitude: _longitude,
              latitude: _latitude,
              onPoint: _select,
              onReady: (ready) {
                if (mounted && ready != _ready) {
                  setState(() => _ready = ready);
                }
              },
            ),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
              child: Center(
                heightFactor: 1,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 560),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Semantics(
                        liveRegion: true,
                        child: Text(
                          _error ??
                              (located
                                  ? 'Место отмечено. Чтобы изменить его, нажмите на карту.'
                                  : 'Нажмите на карту внутри выделенной территории.'),
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontSize: 12,
                            color: _error == null
                                ? muted
                                : Theme.of(context).colorScheme.error,
                          ),
                        ),
                      ),
                      const SizedBox(height: 10),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          onPressed: _ready && located && _error == null
                              ? () {
                                  c.selectPoint(_longitude!, _latitude!);
                                  if (c.form.located && c.error == null) {
                                    Navigator.pop(context, true);
                                  }
                                }
                              : null,
                          icon: const Icon(Icons.check, size: 20),
                          label: const Text('Подтвердить место'),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
