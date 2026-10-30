import 'package:flutter/material.dart';
import '../controller.dart';
import 'common.dart';

/// The existing citizen update notification, floating above the page.
class VersionUpdateNotice extends StatelessWidget {
  const VersionUpdateNotice({super.key, required this.controller});
  final SignalController controller;

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width <= 520;
    final inset = compact ? 16.0 : 20.0;
    final safeBottom = MediaQuery.viewPaddingOf(context).bottom;
    final button = FilledButton.icon(
      key: const ValueKey('apply-version-update'),
      onPressed: controller.busy || controller.preparing || controller.updating
          ? null
          : controller.applyUpdate,
      icon: const Icon(Icons.refresh, size: 16),
      label: Text(controller.updating ? 'Обновляем…' : 'Обновить'),
      style: FilledButton.styleFrom(
        backgroundColor: const Color(0xff2e5140),
        foregroundColor: Colors.white,
        disabledBackgroundColor: const Color(0xff2e5140).withValues(alpha: .55),
        disabledForegroundColor: Colors.white,
        minimumSize: const Size(0, 44),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        textStyle: const TextStyle(
          fontFamily: 'Roboto',
          fontSize: 14,
          fontWeight: FontWeight.w400,
        ),
      ),
    );
    const title = Text(
      'Доступна новая версия',
      style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
    );
    return Positioned(
      left: compact ? inset : null,
      right: inset,
      bottom: safeBottom > inset ? safeBottom : inset,
      child: MapSafe(
        child: Semantics(
          container: true,
          liveRegion: true,
          child: Container(
            key: const ValueKey('version-update-notice'),
            constraints: BoxConstraints(
              maxWidth: MediaQuery.sizeOf(context).width - 32,
            ),
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
            decoration: BoxDecoration(
              color: Colors.white,
              border: Border.all(color: const Color(0xffdce2d5)),
              borderRadius: BorderRadius.circular(12),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x22000000),
                  blurRadius: 30,
                  offset: Offset(0, 8),
                ),
              ],
            ),
            child: DefaultTextStyle(
              style: const TextStyle(
                fontFamily: 'Roboto',
                fontSize: 14,
                height: 1.5,
                color: Color(0xff273730),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (compact) ...[
                    title,
                    const SizedBox(height: 12),
                    Align(alignment: Alignment.centerRight, child: button),
                  ] else
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [title, const SizedBox(width: 18), button],
                    ),
                  if (controller.updateError != null) ...[
                    const SizedBox(height: 12),
                    SizedBox(
                      width: 360,
                      child: Text(
                        controller.updateError!,
                        style: const TextStyle(
                          fontSize: 12,
                          color: Color(0xff9d3b2c),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
