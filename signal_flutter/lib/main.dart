import 'package:flutter/material.dart';
import 'api.dart';
import 'app.dart';
import 'browser.dart';
import 'controller.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final browser = createBrowser();
  runApp(
    SignalApp(
      controller: SignalController(
        api: SignalApi(origin: browser.location),
        browser: browser,
      ),
    ),
  );
}
