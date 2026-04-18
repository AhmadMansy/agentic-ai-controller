// Agentic AI Controller — Arduino Uno firmware
//
// Wiring (all resistors = 220 ohm for LEDs):
//   Pin  9 -> Red LED anode     -> 220R -> GND   (BUSY)
//   Pin 10 -> Yellow LED anode  -> 220R -> GND   (PERMISSION)
//   Pin 11 -> Green LED anode   -> 220R -> GND   (READY)
//   Pin  2 <- Approve button    -> GND           (INPUT_PULLUP, active-low)
//   Pin  3 <- Joystick SW       -> GND           (INPUT_PULLUP, acts as 2nd approve)
//   A0    <- Joystick VRy                        (Y axis for up/down)
//   Joystick 5V -> 5V, Joystick GND -> GND
//   (VRx is unused; leave disconnected or wire to A1 if you want to extend later.)
//
// Serial protocol @ 9600 baud:
//   Host -> Arduino (single chars):
//     'R' red on (busy)
//     'Y' yellow on (permission)
//     'G' green on (ready)
//     'O' all off
//     'T' boot test — cycle all LEDs once
//   Arduino -> Host (newline-terminated):
//     "BTN"  approve button pressed (debounced, edge)
//     "UP"   joystick pushed up (with auto-repeat while held)
//     "DN"   joystick pushed down

const int PIN_RED     = 9;
const int PIN_YELLOW  = 10;
const int PIN_GREEN   = 11;
const int PIN_BTN     = 2;
const int PIN_JOY_SW  = 3;
const int PIN_JOY_Y   = A0;

const int JOY_UP_THRESHOLD = 800;
const int JOY_DN_THRESHOLD = 200;
const int JOY_CENTER_LO    = 400;
const int JOY_CENTER_HI    = 600;

const unsigned long DEBOUNCE_MS   = 40;
const unsigned long JOY_REPEAT_MS = 220;

int lastBtn = HIGH;
int lastSw  = HIGH;
unsigned long lastBtnChange = 0;
unsigned long lastSwChange  = 0;

bool joyCentered = true;
unsigned long lastJoyFire = 0;

void setLeds(bool r, bool y, bool g) {
  digitalWrite(PIN_RED,    r ? HIGH : LOW);
  digitalWrite(PIN_YELLOW, y ? HIGH : LOW);
  digitalWrite(PIN_GREEN,  g ? HIGH : LOW);
}

void setup() {
  pinMode(PIN_RED,    OUTPUT);
  pinMode(PIN_YELLOW, OUTPUT);
  pinMode(PIN_GREEN,  OUTPUT);
  pinMode(PIN_BTN,    INPUT_PULLUP);
  pinMode(PIN_JOY_SW, INPUT_PULLUP);

  Serial.begin(9600);

  // Boot self-test so you can see all 3 LEDs work on power-up.
  setLeds(true, true, true);  delay(250);
  setLeds(true, false, false); delay(180);
  setLeds(false, true, false); delay(180);
  setLeds(false, false, true); delay(180);
  setLeds(false, false, false);
  // Default state = idle/ready (green).
  setLeds(false, false, true);
}

void handleSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    switch (c) {
      case 'R': setLeds(true, false, false); break;
      case 'Y': setLeds(false, true, false); break;
      case 'G': setLeds(false, false, true); break;
      case 'O': setLeds(false, false, false); break;
      case 'T':
        setLeds(true, false, false);  delay(180);
        setLeds(false, true, false);  delay(180);
        setLeds(false, false, true);  delay(180);
        break;
      default: break;  // ignore \n, \r, spaces, unknown chars
    }
  }
}

void handleButtons() {
  unsigned long now = millis();

  int v = digitalRead(PIN_BTN);
  if (v != lastBtn && now - lastBtnChange > DEBOUNCE_MS) {
    lastBtnChange = now;
    if (v == LOW) Serial.println("BTN");
    lastBtn = v;
  }

  int sw = digitalRead(PIN_JOY_SW);
  if (sw != lastSw && now - lastSwChange > DEBOUNCE_MS) {
    lastSwChange = now;
    if (sw == LOW) Serial.println("BTN");  // joystick press = approve too
    lastSw = sw;
  }
}

void handleJoystick() {
  int y = analogRead(PIN_JOY_Y);
  unsigned long now = millis();

  if (y > JOY_CENTER_LO && y < JOY_CENTER_HI) {
    joyCentered = true;
    return;
  }

  bool canFire = joyCentered || (now - lastJoyFire > JOY_REPEAT_MS);
  if (!canFire) return;

  if (y >= JOY_UP_THRESHOLD) {
    Serial.println("UP");
    lastJoyFire = now;
    joyCentered = false;
  } else if (y <= JOY_DN_THRESHOLD) {
    Serial.println("DN");
    lastJoyFire = now;
    joyCentered = false;
  }
}

void loop() {
  handleSerial();
  handleButtons();
  handleJoystick();
}
