import 'package:flutter/material.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';
import '../theme.dart';

class Notice extends StatelessWidget {
  const Notice(
    this.text, {
    super.key,
    this.error = false,
    this.action,
    this.icon = Icons.info_outline,
    this.onDismiss,
  });
  final String text;
  final bool error;
  final Widget? action;
  final IconData icon;
  final VoidCallback? onDismiss;
  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    margin: EdgeInsets.only(bottom: isDesktop(context) ? 0 : 12),
    padding: EdgeInsets.symmetric(
      horizontal: 12,
      vertical: isDesktop(context) ? 10 : 12,
    ),
    decoration: BoxDecoration(
      color: error ? const Color(0xfff9eae4) : paleGreen,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              icon,
              size: 18,
              color: error ? const Color(0xff99593f) : green,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                text,
                style: TextStyle(
                  fontSize: 12,
                  height: 1.5,
                  color: error
                      ? const Color(0xff854c3b)
                      : const Color(0xff48694f),
                ),
              ),
            ),
            if (onDismiss != null)
              SizedBox(
                width: 28,
                height: isDesktop(context) ? 20 : 28,
                child: IconButton(
                  tooltip: 'Скрыть уведомление',
                  onPressed: onDismiss,
                  padding: EdgeInsets.zero,
                  icon: const Icon(Icons.close, size: 15),
                ),
              ),
          ],
        ),
        ?action,
      ],
    ),
  );
}

class FieldLabel extends StatelessWidget {
  const FieldLabel(
    this.text, {
    super.key,
    this.required = false,
    this.optional = false,
  });
  final String text;
  final bool required, optional;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: Wrap(
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: 5,
      children: [
        Text(
          text,
          style: TextStyle(
            fontSize: isDesktop(context) ? 12 : 13,
            height: isDesktop(context) ? 1.3 : null,
            fontWeight: FontWeight.w500,
            color: ink,
          ),
        ),
        if (required)
          const Text(
            '*',
            style: TextStyle(color: Color(0xffa55d4e), fontSize: 13),
          ),
        if (optional)
          const Text(
            'необязательно',
            style: TextStyle(color: muted, fontSize: 11),
          ),
      ],
    ),
  );
}

class ChoiceField extends StatelessWidget {
  const ChoiceField({
    super.key,
    required this.label,
    required this.options,
    required this.value,
    required this.onChanged,
    this.enabled = true,
    this.placeholder = 'Выберите',
    this.compact = false,
  });
  final String label, value, placeholder;
  final List<(String, String)> options;
  final ValueChanged<String> onChanged;
  final bool enabled, compact;
  @override
  Widget build(BuildContext context) {
    final selected = options.any((item) => item.$1 == value) ? value : null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (label.isNotEmpty) FieldLabel(label),
        if (options.length == 1)
          Container(
            width: double.infinity,
            padding: EdgeInsets.symmetric(
              horizontal: 11,
              vertical: compact ? 7 : 11,
            ),
            decoration: BoxDecoration(
              color: isDesktop(context)
                  ? const Color(0xfff0f5f1)
                  : compact
                  ? Colors.white
                  : const Color(0xfff0f5f1),
              borderRadius: BorderRadius.circular(8),
              border: compact && !isDesktop(context)
                  ? Border.all(color: line)
                  : null,
            ),
            child: Text(
              options.first.$2,
              style: TextStyle(fontSize: compact ? 13 : 14, color: ink),
            ),
          )
        else
          Semantics(
            button: true,
            label: label,
            value:
                options.where((item) => item.$1 == selected).firstOrNull?.$2 ??
                placeholder,
            child: InkWell(
              onTap: !enabled || options.isEmpty
                  ? null
                  : () async {
                      Widget choices() => _ChoiceSheet(
                        title: label.isEmpty ? placeholder : label,
                        options: options,
                        selected: selected,
                      );
                      final value = isDesktop(context)
                          ? await showDialog<String>(
                              context: context,
                              builder: (context) => MapSafe(
                                child: Dialog(
                                  child: ConstrainedBox(
                                    constraints: const BoxConstraints(
                                      maxWidth: 480,
                                    ),
                                    child: choices(),
                                  ),
                                ),
                              ),
                            )
                          : await showModalBottomSheet<String>(
                              context: context,
                              useSafeArea: true,
                              isScrollControlled: true,
                              backgroundColor: Colors.white,
                              builder: (context) => MapSafe(child: choices()),
                            );
                      if (value != null) onChanged(value);
                    },
              borderRadius: BorderRadius.circular(9),
              child: InputDecorator(
                isEmpty: selected == null,
                decoration: InputDecoration(
                  enabled: enabled && options.isNotEmpty,
                  contentPadding: EdgeInsets.symmetric(
                    horizontal: 11,
                    vertical: compact ? 8 : 11,
                  ),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        options
                                .where((item) => item.$1 == selected)
                                .firstOrNull
                                ?.$2 ??
                            placeholder,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: compact ? 13 : 14,
                          color: selected == null ? muted : ink,
                        ),
                      ),
                    ),
                    const Icon(
                      Icons.keyboard_arrow_down,
                      size: 19,
                      color: muted,
                    ),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class _ChoiceSheet extends StatefulWidget {
  const _ChoiceSheet({
    required this.title,
    required this.options,
    required this.selected,
  });
  final String title;
  final List<(String, String)> options;
  final String? selected;
  @override
  State<_ChoiceSheet> createState() => _ChoiceSheetState();
}

class _ChoiceSheetState extends State<_ChoiceSheet> {
  final scroll = ScrollController();
  String query = '';
  @override
  void dispose() {
    scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final filtered = widget.options
        .where(
          (item) => item.$2.toLowerCase().replaceAll('ё', 'е').contains(query),
        )
        .toList();
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * .7,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 12, 8, 2),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      widget.title,
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Закрыть выбор',
                    icon: const Icon(Icons.close, size: 21),
                    onPressed: () => Navigator.pop(context),
                  ),
                ],
              ),
            ),
            if (widget.options.length >= 8)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 10),
                child: TextField(
                  key: const ValueKey('choice-search'),
                  style: const TextStyle(fontSize: 14),
                  decoration: InputDecoration(
                    hintText: widget.title == 'Территория'
                        ? 'Поиск территории'
                        : 'Поиск',
                    prefixIcon: const Icon(Icons.search, size: 20),
                  ),
                  onChanged: (value) {
                    setState(
                      () => query = value.trim().toLowerCase().replaceAll(
                        'ё',
                        'е',
                      ),
                    );
                    if (scroll.hasClients) scroll.jumpTo(0);
                  },
                ),
              ),
            Expanded(
              child: filtered.isEmpty
                  ? const Center(
                      child: Text(
                        'Ничего не найдено',
                        style: TextStyle(color: muted),
                      ),
                    )
                  : Scrollbar(
                      controller: scroll,
                      thumbVisibility: true,
                      child: ListView.builder(
                        controller: scroll,
                        padding: const EdgeInsets.fromLTRB(4, 0, 4, 16),
                        itemCount: filtered.length,
                        itemBuilder: (context, index) {
                          final item = filtered[index];
                          final selected = item.$1 == widget.selected;
                          return ListTile(
                            title: Text(
                              item.$2,
                              style: const TextStyle(fontSize: 14),
                            ),
                            selected: selected,
                            selectedColor: green,
                            selectedTileColor: paleGreen,
                            trailing: selected
                                ? const Icon(
                                    Icons.check,
                                    size: 20,
                                    color: green,
                                  )
                                : null,
                            onTap: () => Navigator.pop(context, item.$1),
                          );
                        },
                      ),
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

class SectionCard extends StatelessWidget {
  const SectionCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(17),
  });
  final Widget child;
  final EdgeInsets padding;
  @override
  Widget build(BuildContext context) => Container(
    padding: padding,
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .94),
      border: Border.all(color: const Color(0xffe2eae4)),
      borderRadius: BorderRadius.circular(16),
    ),
    child: child,
  );
}

/// Keep popup controls clickable when an interactive HTML map is underneath.
class MapSafe extends StatelessWidget {
  const MapSafe({super.key, required this.child});
  final Widget child;
  @override
  Widget build(BuildContext context) => PointerInterceptor(child: child);
}
