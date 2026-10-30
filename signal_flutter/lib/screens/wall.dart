import 'package:flutter/material.dart';
import '../controller.dart';
import '../theme.dart';
import '../widgets/appeal_card.dart';
import '../widgets/desktop_appeal_card.dart';
import '../widgets/common.dart';
import '../widgets/responsibility_map.dart';
import '../widgets/wall_filters.dart';

class WallScreen extends StatefulWidget {
  const WallScreen({super.key, required this.controller});
  final SignalController controller;
  @override
  State<WallScreen> createState() => _WallScreenState();
}

class _WallScreenState extends State<WallScreen> {
  final search = TextEditingController();
  bool desktopMapOpen = false;
  @override
  void dispose() {
    search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller, wall = widget.controller.wall;
    final desktop = isDesktop(context);
    return RefreshIndicator(
      onRefresh: c.refreshWall,
      child: ListView(
        key: const PageStorageKey('wall-scroll'),
        padding: EdgeInsets.fromLTRB(
          desktop ? 40 : 16,
          10,
          desktop ? 40 : 16,
          24,
        ),
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  'Обращения жителей',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontSize: desktop ? 28 : 22,
                    color: desktop ? desktopInk : ink,
                  ),
                ),
              ),
              SizedBox(
                width: desktop ? 32 : null,
                height: desktop ? 40 : null,
                child: IconButton(
                  tooltip: 'Обновить обращения',
                  onPressed: c.refreshWall,
                  icon: const Icon(Icons.refresh, size: 20, color: muted),
                ),
              ),
            ],
          ),
          if (c.form.city.isEmpty)
            const _Empty(
              title: 'Выберите город',
              text: 'Здесь появятся обращения его жителей.',
            )
          else ...[
            if (c.organizations.any((o) => o.territories.isNotEmpty)) ...[
              const SizedBox(height: 4),
              if (desktop) ...[
                Row(
                  children: [
                    Expanded(
                      child: Material(
                        color: Colors.white,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                          side: const BorderSide(color: line),
                        ),
                        child: InkWell(
                          key: const ValueKey('desktop-map-toggle'),
                          borderRadius: BorderRadius.circular(10),
                          onTap: () =>
                              setState(() => desktopMapOpen = !desktopMapOpen),
                          child: Padding(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 12,
                              vertical: 12,
                            ),
                            child: Row(
                              children: [
                                const Icon(
                                  Icons.home_work_outlined,
                                  color: green,
                                  size: 21,
                                ),
                                const SizedBox(width: 10),
                                const Expanded(
                                  child: Text(
                                    'Кто отвечает за территорию',
                                    style: TextStyle(
                                      fontSize: 13,
                                      fontWeight: FontWeight.w600,
                                      color: desktopInk,
                                    ),
                                  ),
                                ),
                                Icon(
                                  desktopMapOpen
                                      ? Icons.keyboard_arrow_up
                                      : Icons.keyboard_arrow_down,
                                  size: 19,
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 14),
                    SizedBox(
                      width: 284,
                      height: 46,
                      child: _DesktopMapPreview(
                        controller: c,
                        onTap: () =>
                            setState(() => desktopMapOpen = !desktopMapOpen),
                      ),
                    ),
                  ],
                ),
                if (desktopMapOpen)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: ResponsibilityMap(controller: c, showHeading: false),
                  ),
              ] else
                ResponsibilityMap(controller: c),
              const SizedBox(height: 12),
            ] else
              const SizedBox(height: 7),
            WallFilters(
              controller: c,
              search: search,
              onSearch: (value) {
                c.searchWall(value);
                setState(() {});
              },
            ),
            const SizedBox(height: 13),
            if (c.wallError != null)
              Notice(
                c.wallError!,
                error: true,
                action: TextButton(
                  onPressed: c.refreshWall,
                  child: const Text('Попробовать снова'),
                ),
              ),
            if (wall == null && c.wallLoading)
              const Padding(
                padding: EdgeInsets.all(40),
                child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
              ),
            if (wall != null && wall.items.isEmpty)
              _Empty(
                title: c.search.isEmpty ? 'Пока тихо' : 'Ничего не найдено',
                text: c.search.isEmpty
                    ? 'Новое обращение появится здесь после отправки.'
                    : 'Попробуйте другие слова, адрес или дату.',
              ),
            if (wall != null && desktop)
              LayoutBuilder(
                builder: (context, bounds) => Wrap(
                  spacing: 16,
                  runSpacing: 16,
                  children: wall.items
                      .map(
                        (item) => SizedBox(
                          width: (bounds.maxWidth - 16) / 2,
                          child: DesktopAppealCard(
                            key: ValueKey(item.id),
                            appeal: item,
                            browser: c.browser,
                            origin: c.api.origin,
                          ),
                        ),
                      )
                      .toList(),
                ),
              ),
            if (wall != null && !desktop)
              ...wall.items.map(
                (item) => Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: AppealCard(
                    key: ValueKey(item.id),
                    appeal: item,
                    browser: c.browser,
                    origin: c.api.origin,
                  ),
                ),
              ),
            if (wall != null && wall.pages > 1)
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  IconButton(
                    tooltip: 'Предыдущая страница',
                    onPressed: c.page > 1
                        ? () => c.filterWall(pageNumber: c.page - 1)
                        : null,
                    icon: const Icon(Icons.chevron_left),
                  ),
                  Text(
                    '${c.page} / ${wall.pages}',
                    style: const TextStyle(fontSize: 13),
                  ),
                  IconButton(
                    tooltip: 'Следующая страница',
                    onPressed: c.page < wall.pages
                        ? () => c.filterWall(pageNumber: c.page + 1)
                        : null,
                    icon: const Icon(Icons.chevron_right),
                  ),
                ],
              ),
          ],
        ],
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.title, required this.text});
  final String title, text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 45, horizontal: 20),
    child: Column(
      children: [
        const Icon(Icons.inbox_outlined, size: 36, color: muted),
        const SizedBox(height: 12),
        Text(
          title,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 6),
        Text(
          text,
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 13, color: muted),
        ),
      ],
    ),
  );
}

class _DesktopMapPreview extends StatelessWidget {
  const _DesktopMapPreview({required this.controller, required this.onTap});
  final SignalController controller;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(10),
    child: Stack(
      children: [
        Positioned.fill(
          child: Opacity(
            opacity: .42,
            child: IgnorePointer(
              child: controller.browser.map(
                apiKey: controller.catalog?.mapKey ?? '',
                organizations: controller.organizations,
                organizationId: controller.wallOrganization,
                overview: true,
                preview: true,
              ),
            ),
          ),
        ),
        Positioned.fill(
          child: MapSafe(
            child: Material(
              color: Colors.transparent,
              child: InkWell(
                onTap: onTap,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  child: Row(
                    children: [
                      const Icon(Icons.location_on, size: 26, color: green),
                      const Spacer(),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 8,
                          vertical: 5,
                        ),
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: .85),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: const Text(
                          'Показать карту территорий',
                          style: TextStyle(fontSize: 10, color: desktopInk),
                        ),
                      ),
                      const SizedBox(width: 8),
                      const Icon(Icons.open_in_full, size: 16, color: green),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    ),
  );
}
