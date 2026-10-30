import 'package:flutter/material.dart';

const desktopBreakpoint = 960.0;
const desktopInk = Color(0xff0b1629);
bool isDesktop(BuildContext context) =>
    MediaQuery.sizeOf(context).width >= desktopBreakpoint;

const ink = Color(0xff142f31);
const muted = Color(0xff6b7b78);
const green = Color(0xff165d47);
const line = Color(0xffdce6df);
const surface = Color(0xfff5f9f5);
const paleGreen = Color(0xffecf5ed);

ThemeData signalTheme() => ThemeData(
  useMaterial3: true,
  fontFamily: 'Inter',
  colorScheme: ColorScheme.fromSeed(
    seedColor: green,
    primary: green,
    surface: Colors.white,
    onSurface: ink,
  ),
  scaffoldBackgroundColor: surface,
  textTheme: const TextTheme(
    headlineSmall: TextStyle(
      fontSize: 25,
      fontWeight: FontWeight.w700,
      height: 1.2,
      letterSpacing: -.8,
      color: ink,
    ),
    titleLarge: TextStyle(
      fontSize: 20,
      fontWeight: FontWeight.w700,
      height: 1.3,
      letterSpacing: -.5,
      color: ink,
    ),
    titleMedium: TextStyle(
      fontSize: 16,
      fontWeight: FontWeight.w600,
      height: 1.4,
    ),
    bodyMedium: TextStyle(fontSize: 14, height: 1.5, color: ink),
    bodySmall: TextStyle(fontSize: 12, height: 1.5, color: muted),
  ),
  inputDecorationTheme: InputDecorationTheme(
    isDense: true,
    filled: true,
    fillColor: Colors.white,
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
    hintStyle: const TextStyle(color: Color(0xff929b98), fontSize: 14),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(9),
      borderSide: const BorderSide(color: line),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(9),
      borderSide: const BorderSide(color: line),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(9),
      borderSide: const BorderSide(color: green, width: 1.5),
    ),
  ),
  filledButtonTheme: FilledButtonThemeData(
    style: FilledButton.styleFrom(
      backgroundColor: green,
      foregroundColor: Colors.white,
      minimumSize: const Size(0, 50),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      textStyle: const TextStyle(
        fontFamily: 'Inter',
        fontSize: 15,
        fontWeight: FontWeight.w600,
      ),
    ),
  ),
  iconButtonTheme: IconButtonThemeData(
    style: IconButton.styleFrom(
      foregroundColor: const Color(0xff648071),
      visualDensity: VisualDensity.compact,
    ),
  ),
  dividerTheme: const DividerThemeData(color: line, thickness: 1),
  snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
);
