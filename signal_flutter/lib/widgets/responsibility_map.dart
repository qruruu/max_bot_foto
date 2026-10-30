import 'package:flutter/material.dart';
import '../controller.dart';
import '../models.dart';
import '../theme.dart';
import 'common.dart';

const territoryBlue = Color(0xff438aff);

class ResponsibilityMap extends StatefulWidget {
  const ResponsibilityMap({
    super.key,
    required this.controller,
    this.showHeading = true,
  });
  final bool showHeading;
  final SignalController controller;
  @override
  State<ResponsibilityMap> createState() => _ResponsibilityMapState();
}

class _ResponsibilityMapState extends State<ResponsibilityMap>
    with AutomaticKeepAliveClientMixin<ResponsibilityMap> {
  @override
  bool get wantKeepAlive => true;

  bool expanded = true;

  Future<void> showOrganizations() => showModalBottomSheet<void>(
    context: context,
    useSafeArea: true,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (context) {
      final c = widget.controller;
      return MapSafe(
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.sizeOf(context).height * .7,
          ),
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(4, 0, 4, 18),
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 0, 16, 10),
                child: Text(
                  'Кто отвечает за территорию',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
                ),
              ),
              if (c.organizations.length > 1)
                ListTile(
                  title: const Text(
                    'Все организации',
                    style: TextStyle(fontSize: 14),
                  ),
                  trailing: c.wallOrganization.isEmpty
                      ? const Icon(Icons.check, color: green, size: 20)
                      : null,
                  onTap: () {
                    c.filterWall(organization: '');
                    Navigator.pop(context);
                  },
                ),
              ...c.organizations.map(
                (owner) => ListTile(
                  leading: _Swatch(
                    color: owner.id == c.wallOrganization
                        ? territoryBlue
                        : _ownerColor(owner),
                  ),
                  title: Text(
                    owner.name,
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  subtitle: Text(
                    _territories(owner).join(', '),
                    style: const TextStyle(
                      fontSize: 12,
                      height: 1.5,
                      color: muted,
                    ),
                  ),
                  trailing: owner.id == c.wallOrganization
                      ? const Icon(Icons.check, color: green, size: 20)
                      : null,
                  onTap: () {
                    c.filterWall(organization: owner.id);
                    Navigator.pop(context);
                  },
                ),
              ),
            ],
          ),
        ),
      );
    },
  );

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final c = widget.controller;
    final selected = c.organizations
        .where((o) => o.id == c.wallOrganization)
        .firstOrNull;
    final names = selected == null ? <String>[] : _territories(selected);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: const Color(0xffe3e9e2)),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        children: [
          if (widget.showHeading)
            Semantics(
              button: true,
              hint: expanded ? 'Свернуть карту' : 'Показать карту',
              child: InkWell(
                key: const ValueKey('responsibility-map-toggle'),
                onTap: () => setState(() => expanded = !expanded),
                borderRadius: BorderRadius.circular(14),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(11, 10, 10, 10),
                  child: Row(
                    children: [
                      const Icon(
                        Icons.home_work_outlined,
                        size: 20,
                        color: green,
                      ),
                      const SizedBox(width: 7),
                      const Expanded(
                        child: Text(
                          'Кто отвечает за территорию',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      Icon(
                        expanded
                            ? Icons.keyboard_arrow_up
                            : Icons.keyboard_arrow_down,
                        size: 20,
                        color: muted,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          if (expanded)
            Padding(
              padding: const EdgeInsets.fromLTRB(6, 0, 6, 6),
              child: LayoutBuilder(
                builder: (context, constraints) => SizedBox(
                  height: (constraints.maxWidth / 1.4).clamp(200, 290),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: Stack(
                      children: [
                        Positioned.fill(
                          child: c.browser.map(
                            apiKey: c.catalog?.mapKey ?? '',
                            organizations: c.organizations,
                            organizationId: c.wallOrganization,
                            overview: true,
                            onOrganization: (id) =>
                                c.filterWall(organization: id),
                          ),
                        ),
                        Positioned(
                          left: 7,
                          right: 7,
                          bottom: 7,
                          child: MapSafe(
                            child: Material(
                              color: Colors.white,
                              elevation: 2,
                              shadowColor: Colors.black12,
                              borderRadius: BorderRadius.circular(8),
                              child: InkWell(
                                key: const ValueKey('map-organizations'),
                                borderRadius: BorderRadius.circular(8),
                                onTap: showOrganizations,
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 9,
                                    vertical: 10,
                                  ),
                                  child: Row(
                                    children: [
                                      const _Swatch(color: territoryBlue),
                                      const SizedBox(width: 8),
                                      Expanded(
                                        child: Text.rich(
                                          TextSpan(
                                            children: [
                                              TextSpan(
                                                text:
                                                    selected?.name ??
                                                    'Все организации',
                                                style: const TextStyle(
                                                  fontWeight: FontWeight.w600,
                                                ),
                                              ),
                                              if (names.isNotEmpty)
                                                TextSpan(
                                                  text:
                                                      ' · ${names.take(2).join(', ')}${names.length > 2 ? ' и другие' : ''}',
                                                  style: const TextStyle(
                                                    color: muted,
                                                  ),
                                                ),
                                            ],
                                          ),
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: const TextStyle(
                                            fontSize: 11.5,
                                            height: 1.25,
                                          ),
                                        ),
                                      ),
                                      const SizedBox(width: 4),
                                      const Icon(
                                        Icons.chevron_right,
                                        size: 19,
                                        color: green,
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
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

List<String> _territories(Organization owner) => owner.territories
    .map((item) => item['name'] as String? ?? '')
    .where((name) => name.isNotEmpty)
    .toSet()
    .toList();

Color _ownerColor(Organization owner) => Color(
  int.tryParse(owner.color.replaceFirst('#', 'ff'), radix: 16) ?? 0xff195c46,
);

class _Swatch extends StatelessWidget {
  const _Swatch({required this.color});
  final Color color;
  @override
  Widget build(BuildContext context) => Container(
    width: 18,
    height: 18,
    decoration: BoxDecoration(
      color: color.withValues(alpha: .22),
      border: Border.all(color: color, width: 2),
      borderRadius: BorderRadius.circular(3),
    ),
  );
}
