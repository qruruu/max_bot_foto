import 'package:flutter/material.dart';
import '../controller.dart';
import '../theme.dart';
import 'common.dart';

class WallFilters extends StatelessWidget {
  const WallFilters({
    super.key,
    required this.controller,
    required this.search,
    required this.onSearch,
  });
  final SignalController controller;
  final TextEditingController search;
  final ValueChanged<String> onSearch;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final c = controller;
      final filters = Row(
        children: [
          Expanded(
            flex: 11,
            child: _FilterMenu(
              key: const ValueKey('wall-organization-filter'),
              label: 'Организация',
              icon: Icons.apartment_outlined,
              value: c.wallOrganization,
              options: [
                if (c.organizations.length != 1) ('', 'Все организации'),
                ...c.organizations.map((o) => (o.id, o.name)),
              ],
              emphasized: true,
              onChanged: (id) => c.filterWall(organization: id),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            flex: 10,
            child: _FilterMenu(
              key: const ValueKey('wall-sort-filter'),
              label: 'Порядок обращений',
              icon: constraints.maxWidth < 330 ? null : Icons.swap_vert,
              value: c.sort,
              options: const [
                ('newest', 'Сначала новые'),
                ('oldest', 'Сначала старые'),
                ('organization', 'По организации'),
              ],
              onChanged: (value) => c.filterWall(order: value),
            ),
          ),
        ],
      );
      final query = SizedBox(
        height: 38,
        child: TextField(
          controller: search,
          style: const TextStyle(fontSize: 12.5, height: 1.25),
          maxLength: 200,
          textInputAction: TextInputAction.search,
          onChanged: onSearch,
          onSubmitted: (value) => c.searchWall(value, immediate: true),
          decoration: InputDecoration(
            hintText: 'Поиск по обращениям',
            hintStyle: const TextStyle(
              fontSize: 12.5,
              color: Color(0xff7c827e),
            ),
            counterText: '',
            fillColor: const Color(0xffefeeea),
            prefixIcon: const Icon(
              Icons.search,
              size: 20,
              color: Color(0xff69756e),
            ),
            prefixIconConstraints: const BoxConstraints(
              minWidth: 38,
              minHeight: 36,
            ),
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 12,
              vertical: 9,
            ),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(22),
              borderSide: BorderSide.none,
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(22),
              borderSide: BorderSide.none,
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(22),
              borderSide: const BorderSide(color: Color(0xff91b29d)),
            ),
            suffixIconConstraints: const BoxConstraints.tightFor(
              width: 34,
              height: 36,
            ),
            suffixIcon: search.text.isEmpty
                ? null
                : IconButton(
                    tooltip: 'Очистить поиск',
                    padding: EdgeInsets.zero,
                    icon: const Icon(Icons.close, size: 16),
                    onPressed: () {
                      search.clear();
                      onSearch('');
                      c.searchWall('', immediate: true);
                    },
                  ),
          ),
        ),
      );
      if (isDesktop(context)) {
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: filters),
            const SizedBox(width: 20),
            Expanded(child: query),
          ],
        );
      }
      return Column(children: [filters, const SizedBox(height: 8), query]);
    },
  );
}

class _FilterMenu extends StatelessWidget {
  const _FilterMenu({
    super.key,
    required this.label,
    required this.icon,
    required this.value,
    required this.options,
    required this.onChanged,
    this.emphasized = false,
  });
  final String label, value;
  final IconData? icon;
  final List<(String, String)> options;
  final ValueChanged<String> onChanged;
  final bool emphasized;

  @override
  Widget build(BuildContext context) {
    final selected = options.where((item) => item.$1 == value).firstOrNull;
    return PopupMenuButton<String>(
      tooltip: label,
      initialValue: value,
      position: PopupMenuPosition.under,
      onSelected: onChanged,
      itemBuilder: (_) => options
          .map(
            (item) => PopupMenuItem(
              value: item.$1,
              height: 44,
              child: MapSafe(
                child: Text(item.$2, style: const TextStyle(fontSize: 13)),
              ),
            ),
          )
          .toList(),
      child: Container(
        height: 38,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        decoration: BoxDecoration(
          color: const Color(0xfffffdf9),
          border: Border.all(color: const Color(0xffe8e8e1)),
          borderRadius: BorderRadius.circular(11),
        ),
        child: Row(
          children: [
            if (icon != null) ...[
              Icon(icon, size: 18, color: green),
              const SizedBox(width: 5),
            ],
            Expanded(
              child: Text(
                selected?.$2 ?? label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 12,
                  letterSpacing: 0,
                  height: 1.2,
                  fontWeight: emphasized ? FontWeight.w600 : FontWeight.w400,
                  color: emphasized ? green : const Color(0xff343d37),
                ),
              ),
            ),
            const SizedBox(width: 3),
            const Icon(
              Icons.keyboard_arrow_down,
              size: 17,
              color: Color(0xff4a6d5a),
            ),
          ],
        ),
      ),
    );
  }
}
