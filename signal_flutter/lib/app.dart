import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'controller.dart';
import 'screens/intake.dart';
import 'screens/wall.dart';
import 'theme.dart';
import 'widgets/common.dart';
import 'widgets/update_notice.dart';

class SignalApp extends StatelessWidget {
  const SignalApp({super.key, required this.controller});
  final SignalController controller;
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Сигнал — обращения жителей',
    debugShowCheckedModeBanner: false,
    theme: signalTheme(),
    locale: const Locale('ru'),
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    supportedLocales: const [Locale('ru')],
    home: SignalHome(controller: controller),
  );
}

class SignalHome extends StatefulWidget {
  const SignalHome({super.key, required this.controller});
  final SignalController controller;
  @override
  State<SignalHome> createState() => _SignalHomeState();
}

class _SignalHomeState extends State<SignalHome> {
  @override
  void initState() {
    super.initState();
    widget.controller.initialize();
  }

  @override
  void dispose() {
    widget.controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: widget.controller,
    builder: (context, _) {
      final c = widget.controller;
      final desktop = isDesktop(context);
      final page = ColoredBox(
        color: const Color(0xffeaf0ed),
        child: Center(
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: desktop ? 1440 : 480),
            child: Scaffold(
              backgroundColor: surface,
              body: SafeArea(
                bottom: false,
                child: Column(
                  children: [
                    Container(
                      padding: EdgeInsets.symmetric(
                        horizontal: desktop ? 40 : 19,
                        vertical: desktop ? 8 : 14,
                      ),
                      decoration: const BoxDecoration(
                        color: Color(0xfff7faf7),
                        border: Border(
                          bottom: BorderSide(color: Color(0xffe3ebe5)),
                        ),
                      ),
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          Row(
                            children: [
                              InkWell(
                                onTap: c.showWall,
                                borderRadius: BorderRadius.circular(10),
                                child: Row(
                                  children: [
                                    Container(
                                      width: desktop ? 40 : 35,
                                      height: desktop ? 40 : 35,
                                      decoration: BoxDecoration(
                                        borderRadius: BorderRadius.circular(10),
                                        gradient: const LinearGradient(
                                          colors: [
                                            Color(0xff216f56),
                                            Color(0xff11513d),
                                          ],
                                        ),
                                      ),
                                      child: const Icon(
                                        Icons.sensors,
                                        color: Colors.white,
                                        size: 25,
                                      ),
                                    ),
                                    const SizedBox(width: 10),
                                    Text(
                                      'Сигнал',
                                      style: TextStyle(
                                        color: desktop ? desktopInk : ink,
                                        fontSize: desktop ? 28 : 24,
                                        fontWeight: FontWeight.w700,
                                        letterSpacing: -.8,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Align(
                                  alignment: Alignment.centerRight,
                                  child: _City(controller: c),
                                ),
                              ),
                            ],
                          ),
                          if (desktop)
                            Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                _DesktopNav(
                                  label: 'Стена города',
                                  selected: c.tab == 0,
                                  onTap: c.showWall,
                                ),
                                const SizedBox(width: 8),
                                _DesktopNav(
                                  label: 'Сообщить о проблеме',
                                  selected: c.tab == 1,
                                  onTap: c.locked ? null : c.newAppeal,
                                ),
                              ],
                            ),
                        ],
                      ),
                    ),
                    if (!c.online)
                      const Padding(
                        padding: EdgeInsets.fromLTRB(16, 12, 16, 0),
                        child: Notice(
                          'Нет интернета. Черновик сохранится на устройстве.',
                          icon: Icons.wifi_off,
                        ),
                      ),
                    if (c.storageError)
                      const Padding(
                        padding: EdgeInsets.fromLTRB(16, 12, 16, 0),
                        child: Notice(
                          'Не закрывайте вкладку до отправки: браузер не разрешил сохранить черновик.',
                        ),
                      ),
                    if (c.catalogError != null)
                      Padding(
                        padding: EdgeInsets.fromLTRB(
                          desktop ? 40 : 16,
                          12,
                          desktop ? 40 : 16,
                          0,
                        ),
                        child: Notice(
                          c.catalogError!,
                          error: true,
                          action: TextButton(
                            onPressed: c.retryCatalog,
                            child: const Text('Повторить загрузку'),
                          ),
                        ),
                      ),
                    if (c.receipt != null)
                      Padding(
                        padding: EdgeInsets.fromLTRB(
                          desktop ? 40 : 16,
                          12,
                          desktop ? 40 : 16,
                          0,
                        ),
                        child: Notice(
                          'Обращение ${c.receipt} отправлено. Ответ организации появится в его карточке.',
                          icon: Icons.check_circle_outline,
                          onDismiss: c.dismissReceipt,
                        ),
                      ),
                    Expanded(
                      child: c.loading
                          ? const Center(
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : c.tab == 0
                          ? WallScreen(controller: c)
                          : IntakeScreen(controller: c),
                    ),
                  ],
                ),
              ),
              bottomNavigationBar: desktop
                  ? null
                  : Container(
                      decoration: const BoxDecoration(
                        color: Colors.white,
                        border: Border(
                          top: BorderSide(color: Color(0xffdfe8e0)),
                        ),
                      ),
                      child: SafeArea(
                        top: false,
                        child: Padding(
                          padding: const EdgeInsets.fromLTRB(10, 6, 10, 7),
                          child: Row(
                            children: [
                              Expanded(
                                child: _NavItem(
                                  label: 'Стена города',
                                  icon: Icons.format_list_bulleted,
                                  selected: c.tab == 0,
                                  onTap: c.showWall,
                                ),
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: _NavItem(
                                  label: 'Сообщить о проблеме',
                                  icon: Icons.add,
                                  selected: c.tab == 1,
                                  onTap: c.locked ? null : c.newAppeal,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
            ),
          ),
        ),
      );
      return Stack(
        fit: StackFit.expand,
        children: [
          page,
          if (c.updateAvailable) VersionUpdateNotice(controller: c),
        ],
      );
    },
  );
}

class _City extends StatelessWidget {
  const _City({required this.controller});
  final SignalController controller;
  @override
  Widget build(BuildContext context) {
    final cities = controller.catalog?.cities ?? [];
    final content = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(
          Icons.location_on_outlined,
          size: 16,
          color: Color(0xff4e6c61),
        ),
        const SizedBox(width: 4),
        Flexible(
          child: Text(
            controller.form.city.isEmpty
                ? 'Выберите город'
                : controller.form.city,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 11.5, color: Color(0xff4e6c61)),
          ),
        ),
        if (cities.length > 1)
          const Icon(Icons.keyboard_arrow_down, size: 14, color: muted),
      ],
    );
    if (cities.length <= 1) return content;
    return PopupMenuButton<String>(
      tooltip: 'Выбрать город',
      enabled: !controller.locked,
      onSelected: controller.selectCity,
      itemBuilder: (_) => cities
          .map(
            (city) => PopupMenuItem(
              value: city,
              child: MapSafe(child: Text(city)),
            ),
          )
          .toList(),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: content,
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.label,
    required this.icon,
    required this.selected,
    this.onTap,
  });
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => Semantics(
    selected: selected,
    button: true,
    child: Material(
      color: selected ? const Color(0xffeaf4eb) : Colors.transparent,
      borderRadius: BorderRadius.circular(10),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 7, horizontal: 2),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 23, color: selected ? green : muted),
              const SizedBox(height: 3),
              Text(
                label,
                maxLines: 1,
                style: TextStyle(
                  fontSize: 10.5,
                  fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                  color: selected ? green : muted,
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _DesktopNav extends StatelessWidget {
  const _DesktopNav({required this.label, required this.selected, this.onTap});
  final String label;
  final bool selected;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    selected: selected,
    child: TextButton(
      onPressed: onTap,
      style: TextButton.styleFrom(
        backgroundColor: selected
            ? const Color(0xffe6f1eb)
            : Colors.transparent,
        foregroundColor: selected ? green : desktopInk,
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
        minimumSize: const Size(0, 36),
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
        textStyle: TextStyle(
          fontSize: 12,
          fontFamily: 'Inter',
          fontWeight: selected ? FontWeight.w500 : FontWeight.w400,
        ),
      ),
      child: Text(label),
    ),
  );
}
