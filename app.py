#!/usr/bin/env python3
"""
Medical Reminder Agent - Comprehensive Health Assistant Bot
Features: Smart reminders, conversational AI, task management with edit functionality
"""

import asyncio
import logging
import sqlite3
import uuid
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
import json

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import pytz
from tzlocal import get_localzone_name
import httpx
import os
os.environ['OLLAMA_HOST'] = 'http://host.docker.internal:11434'


# Timezone setup
utc = timezone.utc
try:
    from tzlocal import get_localzone_name
    tz_name = get_localzone_name()
    if tz_name is None:
        tz_name = "UTC"
except:
    tz_name = "UTC"

local_tz = pytz.timezone(tz_name)


# Logging setup with UTF-8 encoding for Windows compatibility
import sys
import io

# Configure logging with UTF-8 encoding
class UTF8StreamHandler(logging.StreamHandler):
    def __init__(self):
        super().__init__()
        # Force UTF-8 encoding for console output
        if sys.platform.startswith('win'):
            # For Windows, wrap stdout with UTF-8 encoding
            self.stream = io.TextIOWrapper(
                sys.stdout.buffer, 
                encoding='utf-8', 
                errors='replace'
            )
        else:
            self.stream = sys.stdout

# Setup logging handlers
file_handler = logging.FileHandler('medical_bot.log', encoding='utf-8')
console_handler = UTF8StreamHandler()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)

# Database setup
class DatabaseManager:
    def __init__(self, db_path: str = "medical_bot.db"):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def init_database(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                timezone TEXT DEFAULT 'America/New_York',
                preferences TEXT,
                created_at TEXT,
                last_active TEXT
            )
        ''')
        
        # Tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                task_name TEXT NOT NULL,
                category TEXT,
                urgency TEXT,
                scheduled_time TEXT,
                local_time_display TEXT,
                status TEXT DEFAULT 'scheduled',
                created_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Task logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task_id TEXT,
                action TEXT,
                timestamp TEXT,
                details TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (task_id) REFERENCES tasks (id)
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ Database initialized successfully")

@dataclass
class UserProfile:
    user_id: int
    first_name: str
    username: Optional[str] = None
    timezone: str = 'America/New_York'
    preferences: Dict[str, Any] = None
    created_at: Optional[str] = None
    last_active: Optional[str] = None

class TaskManager:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def create_task(self, user_id: int, task_name: str, category: str, urgency: str, 
                   scheduled_time: str, local_time_display: str) -> str:
        task_id = str(uuid.uuid4())
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO tasks (id, user_id, task_name, category, urgency, scheduled_time, 
                             local_time_display, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (task_id, user_id, task_name, category, urgency, scheduled_time, 
              local_time_display, datetime.now(utc).isoformat()))
        
        conn.commit()
        conn.close()
        
        self.log_action(user_id, task_id, 'created', f'Task created: {task_name}')
        logger.info(f"✅ Created task {task_id} for user {user_id}: {task_name}")
        return task_id
    
    def get_pending_tasks(self, user_id: int) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, task_name, category, urgency, scheduled_time, local_time_display
            FROM tasks 
            WHERE user_id = ? AND status = 'scheduled'
            ORDER BY scheduled_time ASC
        ''', (user_id,))
        
        tasks = []
        for row in cursor.fetchall():
            tasks.append({
                'id': row[0],
                'task_name': row[1],
                'category': row[2],
                'urgency': row[3],
                'scheduled_time': row[4],
                'local_time_display': row[5]
            })
        
        conn.close()
        return tasks
    
    def complete_task(self, task_id: str, user_id: int) -> bool:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE tasks 
            SET status = 'completed', completed_at = ?
            WHERE id = ? AND user_id = ? AND status = 'scheduled'
        ''', (datetime.now(utc).isoformat(), task_id, user_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        if success:
            self.log_action(user_id, task_id, 'completed', 'Task marked as completed')
            logger.info(f"✅ Completed task {task_id} for user {user_id}")
        
        return success
    
    def dismiss_task(self, task_id: str, user_id: int) -> bool:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE tasks 
            SET status = 'dismissed', completed_at = ?
            WHERE id = ? AND user_id = ? AND status = 'scheduled'
        ''', (datetime.now(utc).isoformat(), task_id, user_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        if success:
            self.log_action(user_id, task_id, 'dismissed', 'Task dismissed by user')
            logger.info(f"❌ Dismissed task {task_id} for user {user_id}")
        
        return success
    
    def update_task_time(self, task_id: str, user_id: int, new_time: str, new_display_time: str) -> bool:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE tasks 
            SET scheduled_time = ?, local_time_display = ?
            WHERE id = ? AND user_id = ? AND status = 'scheduled'
        ''', (new_time, new_display_time, task_id, user_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        if success:
            self.log_action(user_id, task_id, 'time_updated', f'Time updated to {new_display_time}')
            logger.info(f"⏰ Updated time for task {task_id} for user {user_id}")
        
        return success
    
    def update_task_name(self, task_id: str, user_id: int, new_name: str) -> bool:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE tasks 
            SET task_name = ?
            WHERE id = ? AND user_id = ? AND status = 'scheduled'
        ''', (new_name, task_id, user_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        if success:
            self.log_action(user_id, task_id, 'name_updated', f'Name updated to {new_name}')
            logger.info(f"📝 Updated name for task {task_id} for user {user_id}")
        
        return success
    
    def find_task_by_partial_name(self, user_id: int, partial_name: str) -> Optional[Dict[str, Any]]:
        pending_tasks = self.get_pending_tasks(user_id)
        partial_name_lower = partial_name.lower()
        
        # Try exact match first
        for task in pending_tasks:
            if partial_name_lower == task['task_name'].lower():
                return task
        
        # Try partial match
        for task in pending_tasks:
            if partial_name_lower in task['task_name'].lower():
                return task
        
        return None
    
    def cancel_tasks_by_name(self, user_id: int, task_name: str) -> int:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Find matching tasks
        cursor.execute('''
            SELECT id FROM tasks 
            WHERE user_id = ? AND status = 'scheduled' AND LOWER(task_name) LIKE LOWER(?)
        ''', (user_id, f'%{task_name}%'))
        
        task_ids = [row[0] for row in cursor.fetchall()]
        
        if task_ids:
            placeholders = ','.join(['?' for _ in task_ids])
            cursor.execute(f'''
                UPDATE tasks 
                SET status = 'dismissed', completed_at = ?
                WHERE id IN ({placeholders})
            ''', [datetime.now(utc).isoformat()] + task_ids)
            
            conn.commit()
            
            for task_id in task_ids:
                self.log_action(user_id, task_id, 'cancelled', f'Task cancelled by user request')
        
        conn.close()
        logger.info(f"❌ Cancelled {len(task_ids)} tasks matching '{task_name}' for user {user_id}")
        return len(task_ids)
    
    def log_action(self, user_id: int, task_id: str, action: str, details: str):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO task_logs (user_id, task_id, action, timestamp, details)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, task_id, action, datetime.now(utc).isoformat(), details))
        
        conn.commit()
        conn.close()

class IntentAgent:
    def classify_intent(self, text: str) -> str:
        text = text.lower().strip()
        
        # Cancel patterns - highest priority
        cancel_patterns = [
            r'\b(cancel|delete|remove|stop)\b.*\b(reminder|task|alarm)\b',
            r'\b(cancel|delete|remove|stop)\b.*\b(take|taking|do|doing)\b',
            r'\b(don\'t|dont|do not)\b.*\b(remind|need|want)\b',
            r'\b(forget|ignore|skip)\b.*\b(reminder|task|that)\b',
            r'\b(cancel|delete|remove|clear)\b',
            r'\b(nevermind|never mind|no longer|not anymore)\b'
        ]
        
        # Task creation patterns
        task_creation_patterns = [
            r'\b(remind me|remind em|set reminder|schedule.*reminder)\b',
            r'\b(reminder.*for|reminder.*at|reminder.*in)\b',
            r'\b(remind.*to.*do|remind.*about)\b',
            r'\b(set.*task|schedule.*task)\b',
            r'\b(alert.*me|notify.*me)\b.*\b(at|in|for)\b',
            r'\b(remember.*to|don\'t forget)\b',
            r'\b(wake.*me|call.*me)\b.*\b(at|in)\b'
        ]
        
        # Edit patterns
        edit_patterns = [
            r'\b(edit.*time.*of|change.*time.*of|modify.*time.*of|update.*time.*of)\b',
            r'\b(edit.*name.*of|change.*name.*of|modify.*name.*of|update.*name.*of|rename)\b',
            r'\b(edit.*reminder|change.*reminder|modify.*reminder)\b'
        ]
        
        # Status patterns
        status_patterns = [
            r'\b(show|list|what|view|see|check)\b.*\b(task|reminder|schedule|upcoming)\b',
            r'\b(my.*task|my.*reminder|what.*task|what.*reminder)\b',
            r'\b(pending|scheduled|upcoming|active)\b.*\b(task|reminder)\b'
        ]
        
        # Greeting patterns
        greeting_patterns = [
            r'^\b(hello|hi|hey|good morning|good afternoon|good evening|start|begin)\b',
            r'^\b(what\'s up|wassup|how are you|how\'s it going)\b'
        ]
        
        # Check patterns in priority order
        for pattern in cancel_patterns:
            if re.search(pattern, text):
                return 'cancel'
        
        for pattern in edit_patterns:
            if re.search(pattern, text):
                return 'edit'
        
        for pattern in task_creation_patterns:
            if re.search(pattern, text):
                return 'task_creation'
        
        for pattern in status_patterns:
            if re.search(pattern, text):
                return 'status'
        
        for pattern in greeting_patterns:
            if re.search(pattern, text):
                return 'greeting'
        
        return 'general_conversation'

class ConversationalAgent:
    def __init__(self):
        # Based on your setup: Ollama 0.6.5 with Mistral on port 11434
        self.api_url = "http://127.0.0.1:11434/api/generate"
        self.model = "mistral:latest"  # Use the exact model name from your system
        self.format_type = "ollama"
        logger.info(f"🎯 ConversationalAgent configured for: {self.api_url} with model {self.model}")
    
    async def find_working_endpoint(self):
        """Test if the configured endpoint is working"""
        try:
            # First request can take 30-60 seconds to load the model
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Use the exact same format that worked in PowerShell
                test_payload = {
                    "model": "mistral:latest",
                    "prompt": "Hi",
                    "stream": False
                }
                logger.info(f"🔍 Testing endpoint: {self.api_url}")
                logger.info(f"📋 Payload: {test_payload}")
                logger.info(f"⏳ This may take 30-60 seconds to load the model...")
                
                response = await client.post(self.api_url, json=test_payload)
                
                logger.info(f"📡 Response status: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"✅ Ollama connection successful!")
                    logger.info(f"📝 Response: {result.get('response', '')[:100]}...")
                    logger.info(f"🚀 Model is now loaded - future requests will be faster!")
                    return True
                else:
                    logger.error(f"❌ Bad response: {response.status_code}")
                    logger.error(f"📄 Response text: {response.text}")
                    return False
                    
        except httpx.TimeoutException as e:
            logger.error(f"❌ Timeout connecting to Ollama (>60s): {e}")
            logger.error("💡 Try running 'ollama run mistral:latest' first to pre-load the model")
            return False
        except httpx.ConnectError as e:
            logger.error(f"❌ Connection error to Ollama: {e}")
            logger.error("💡 Make sure Ollama is running with 'ollama serve'")
            return False
        except Exception as e:
            logger.error(f"❌ Connection test failed: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"🔍 Full traceback: {traceback.format_exc()}")
            return False
    
    async def get_response(self, user_message: str, user_name: str = "User") -> str:
        try:
            # Test connection first time (this loads the model)
            if not hasattr(self, '_connection_tested'):
                logger.info("🔄 First request - testing connection and loading model...")
                connection_ok = await self.find_working_endpoint()
                self._connection_tested = True
                if not connection_ok:
                    return f"Hi {user_name}! I'm having trouble connecting to Ollama. You can still use me for setting reminders! Try saying 'Remind me to take medication at 8am' 😊"
            
            system_prompt = f"""You are a helpful, empathetic medical assistant. The user's name is {user_name}. 
            Provide warm, supportive responses about health topics, medication information, wellness tips, or general conversation.
            Keep responses conversational, helpful, and encouraging. Always suggest consulting healthcare providers for medical decisions.
            Be brief but caring in your responses."""
            
            # Use the exact same format that worked in PowerShell
            payload = {
                "model": "mistral:latest",
                "prompt": f"{system_prompt}\n\nUser: {user_message}\nAssistant:",
                "stream": False
            }
            
            # Use consistent 60-second timeout for all conversation requests
            timeout = 60.0
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                logger.info(f"🤖 Sending request to Ollama: {user_message[:50]}...")
                if not hasattr(self, '_model_loaded'):
                    logger.info(f"⏳ Model loading - this may take up to 60 seconds...")
                
                response = await client.post(self.api_url, json=payload)
                
                logger.info(f"📡 Ollama response status: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    ai_response = result.get('response', '').strip()
                    
                    # Mark model as loaded after first successful response
                    self._model_loaded = True
                    
                    if ai_response:
                        logger.info(f"✅ Got AI response: {ai_response[:100]}...")
                        return ai_response
                    else:
                        logger.warning("⚠️ Empty response from Ollama")
                        return f"Hi {user_name}! I heard you, but I'm having trouble forming a response. How can I help you with health reminders? 🏥"
                else:
                    logger.error(f"❌ Bad response from Ollama: {response.status_code} - {response.text}")
                    return f"Hi {user_name}! I'm having trouble with my AI right now. You can still use me for reminders! 📋"
                
        except httpx.ConnectError as e:
            logger.error(f"❌ Cannot connect to Ollama: {e}")
            return f"Hi {user_name}! I can't reach Ollama right now. You can still use me for setting reminders! Try saying 'Remind me to take medication at 8am' 😊"
        except httpx.TimeoutException:
            logger.error(f"❌ Timeout from Ollama")
            return f"Hi {user_name}! Ollama is taking too long to respond. Let me help you with reminders instead! 📋"
        except Exception as e:
            logger.error(f"❌ ConversationalAgent error: {e}")
            return f"Hi {user_name}! I'm having some technical difficulties, but I can still help you set up health reminders! 🏥"

class TaskExtractor:
    def __init__(self):
        # Based on your setup: Ollama 0.6.5 with Mistral on port 11434
        self.api_url = "http://127.0.0.1:11434/api/generate"
        self.model = "mistral:latest"  # Use the exact model name from your system
        logger.info(f"🎯 TaskExtractor configured for: {self.api_url} with model {self.model}")
    
    async def find_working_endpoint(self):
        """Test if the configured endpoint is working"""
        try:
            # First request can take 30-60 seconds to load the model
            async with httpx.AsyncClient(timeout=60.0) as client:
                test_payload = {
                    "model": "mistral:latest",
                    "prompt": "Test",
                    "stream": False
                }
                logger.info(f"🔍 Testing TaskExtractor endpoint: {self.api_url}")
                response = await client.post(self.api_url, json=test_payload)
                
                if response.status_code == 200:
                    logger.info(f"✅ TaskExtractor Ollama connection successful!")
                    return True
                else:
                    logger.error(f"❌ TaskExtractor bad response: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ TaskExtractor connection test failed: {e}")
            return False
    
    async def extract_tasks(self, text: str) -> List[Dict[str, str]]:
        try:
            # Test connection first time
            if not hasattr(self, '_connection_tested'):
                connection_ok = await self.find_working_endpoint()
                self._connection_tested = True
                if not connection_ok:
                    logger.warning("❌ No working Ollama endpoint for task extraction")
                    return []
            
            prompt = f"""
Extract medical/health reminders from this message. If NO reminders are requested, respond with "NO_TASKS_FOUND".

For valid reminders, extract each in this format:
TASK_START
Task: [exact task name as user said it]
Time: [EXACT time as mentioned - do not convert or add explanations]
Urgency: [Relaxed/General/Urgent]
Category: [Medication/Exercise/Appointment/Other]
TASK_END

IMPORTANT: 
- Keep the Time field EXACTLY as mentioned by the user
- Do NOT add explanations like "(Assuming 14:05 is a 24-hour clock format)"
- Do NOT convert times - copy them exactly

Examples:
- If user says "14:05", Time should be: 14:05
- If user says "10:30am", Time should be: 10:30am
- If user says "in 30 minutes", Time should be: in 30 minutes

Message: "{text}"
"""
            
            # Use the exact same format that worked in PowerShell
            payload = {
                "model": "mistral:latest",
                "prompt": prompt,
                "stream": False
            }
            
            # Task extraction needs more time due to complex prompt
            async with httpx.AsyncClient(timeout=60.0) as client:
                logger.info(f"🧠 Extracting tasks from: {text[:50]}...")
                logger.info(f"⏳ Task extraction may take up to 60 seconds...")
                
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                
                result = response.json()
                llm_response = result.get('response', '').strip()
                
                logger.info(f"🧠 LLM Response: {llm_response[:200]}...")
                
                if "NO_TASKS_FOUND" in llm_response:
                    return []
                
                return self.parse_llm_response(llm_response)
                
        except httpx.ConnectError:
            logger.error(f"❌ Cannot connect to Ollama for task extraction")
            return []
        except httpx.TimeoutException:
            logger.error(f"❌ Timeout during task extraction (>60s)")
            return []
        except Exception as e:
            logger.error(f"❌ TaskExtractor error: {e}")
            return []
    
    def parse_llm_response(self, response: str) -> List[Dict[str, str]]:
        tasks = []
        task_blocks = re.findall(r'TASK_START(.*?)TASK_END', response, re.DOTALL)
        
        for block in task_blocks:
            task_data = {}
            for line in block.strip().split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    task_data[key.strip().lower()] = value.strip()
            
            if 'task' in task_data and 'time' in task_data:
                parsed_time = self.parse_time(task_data['time'])
                if parsed_time:
                    tasks.append({
                        'task': task_data['task'],
                        'time': task_data['time'],
                        'parsed_time': parsed_time,
                        'category': task_data.get('category', 'Other'),
                        'urgency': task_data.get('urgency', 'General')
                    })
                    logger.info(f"📋 Extracted task: {task_data['task']} at {parsed_time}")
        
        return tasks
    
    def parse_time(self, time_str: str) -> Optional[datetime]:
        try:
            now = datetime.now(local_tz)
            original_time_str = time_str
            time_str = time_str.lower().strip()
            
            logger.info(f"🕐 Parsing time: '{time_str}'")
            
            # Clean up the time string
            time_str = re.sub(r'\s*\(.*?\)\s*', ' ', time_str)
            time_str = re.sub(r'\btoday\b', '', time_str)
            time_str = re.sub(r'\bassuming.*$', '', time_str)
            time_str = re.sub(r'\b(is\s+a\s+24-hour\s+clock\s+format)\b', '', time_str)
            time_str = time_str.strip()
            
            # Relative times
            if "in" in time_str:
                if "minute" in time_str or "min" in time_str:
                    match = re.search(r'(\d+)', time_str)
                    if match:
                        minutes = int(match.group(1))
                        result = now + timedelta(minutes=minutes)
                        logger.info(f"✅ Parsed relative time: {result}")
                        return result
                elif "hour" in time_str:
                    match = re.search(r'(\d+)', time_str)
                    if match:
                        hours = int(match.group(1))
                        result = now + timedelta(hours=hours)
                        logger.info(f"✅ Parsed relative time: {result}")
                        return result
            
            # 24-hour format
            match_24h = re.search(r'\b(\d{1,2}):(\d{2})\b', time_str)
            if match_24h:
                hour = int(match_24h.group(1))
                minute = int(match_24h.group(2))
                
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if result <= now:
                        result += timedelta(days=1)
                        logger.info("⏭️ Moved to next day")
                    logger.info(f"✅ Parsed 24-hour time: {result}")
                    return result
            
            # 12-hour format with AM/PM
            if any(marker in time_str for marker in ['pm', 'am', 'p.m', 'a.m']):
                time_patterns = [
                    r'(\d{1,2}:\d{2})\s*([ap])\.?m',
                    r'(\d{1,2})\s*([ap])\.?m',
                ]
                
                for pattern in time_patterns:
                    match = re.search(pattern, time_str)
                    if match:
                        time_part = match.group(1)
                        am_pm = match.group(2).upper()
                        
                        logger.info(f"🎯 Found time pattern: '{time_part}' with '{am_pm}M'")
                        
                        try:
                            if ':' in time_part:
                                hour, minute = map(int, time_part.split(':'))
                            else:
                                hour = int(time_part)
                                minute = 0
                            
                            # Convert to 24-hour format
                            if am_pm == 'P' and hour != 12:
                                hour += 12
                            elif am_pm == 'A' and hour == 12:
                                hour = 0
                            
                            result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                            if result <= now:
                                result += timedelta(days=1)
                                logger.info("⏭️ Moved to next day")
                            
                            logger.info(f"✅ Parsed 12-hour time: {result}")
                            return result
                            
                        except (ValueError, IndexError) as ve:
                            logger.warning(f"⚠️ Time parsing error: {ve}")
                            continue
            
            # Hour-only fallback
            hour_match = re.search(r'\b(\d{1,2})\b', time_str)
            if hour_match:
                hour = int(hour_match.group(1))
                if 1 <= hour <= 24:
                    actual_hour = hour if hour <= 23 else 23
                    result = now.replace(hour=actual_hour, minute=0, second=0, microsecond=0)
                    if result <= now:
                        result += timedelta(days=1)
                        logger.info("⏭️ Moved to next day")
                    logger.info(f"✅ Parsed hour-only time: {result}")
                    return result
            
            logger.warning(f"❌ Could not parse time: '{time_str}' (original: '{original_time_str}')")
            return None
            
        except Exception as e:
            logger.error(f"❌ Time parsing exception: {e}")
            return None

class MedicalReminderBot:
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.user_profile = UserProfile
        self.task_manager = TaskManager(self.db_manager)
        self.intent_agent = IntentAgent()
        self.task_extractor = TaskExtractor()
        self.conversational_agent = ConversationalAgent()
        self.scheduler = AsyncIOScheduler(timezone=local_tz)
        self.scheduler.start()
        logger.info("✅ Medical Reminder Bot initialized")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_id = user.id
        
        # Create or update user profile
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (user_id, first_name, username, created_at, last_active)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, user.first_name, user.username, 
                  datetime.now(utc).isoformat(), datetime.now(utc).isoformat()))
            logger.info(f"✅ Created default profile for user {user_id}")
        else:
            cursor.execute('''
                UPDATE users SET first_name = ?, username = ?, last_active = ?
                WHERE user_id = ?
            ''', (user.first_name, user.username, datetime.now(utc).isoformat(), user_id))
            logger.info(f"✅ Updated profile for user {user_id}")
        
        conn.commit()
        conn.close()
        
        welcome_msg = f"""
🏥 **Medical Reminder Assistant**
Welcome, {user.first_name}! I'm here to help you manage your health reminders.

🎯 **I can help you:**
• Set medication reminders
• Schedule exercise notifications  
• Track appointment alerts
• Monitor your health routine

💬 **Just talk naturally! Say things like:**
• "Remind me to take pills at 8am"
• "Remind me to take Adderall at 13:05"
• "Set exercise reminder in 30 minutes"
• "Show my tasks"

⏰ **Current time:** 
🏠 Local: {datetime.now(local_tz).strftime('%I:%M %p %Z')}
🌍 UTC: {datetime.now(utc).strftime('%I:%M %p UTC')}

Type /help for more commands or just start chatting!
        """
        
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')
        logger.info(f"👋 User {user_id} started the bot")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_msg = """
🆘 **Available Commands:**

/start - Start the bot
/help - Show this help message
/status - Show all your tasks
/pending - Show upcoming reminders
/completed - Show completed tasks (last 7 days)
/dismissed - Show dismissed tasks (last 7 days)

💬 **Natural Conversation:**
I'm Smart Reminder Agent, your AI medical assistant! Chat with me about anything:
• "What's the weather like today?"
• "Tell me a joke"
• "How can I reduce stress?"
• "Remind me to take medication at 9am"
• "Remind me to take Adderall at 13:05"
• "What should I eat for better sleep?"

⏰ **Time Formats for Reminders:**
• "in 30 minutes" or "in 2 mins"
• "at 8:00 am" or "at 8 am"
• "at 13:05" (24-hour format)
• "tomorrow 2pm"
• "8:30 pm"

✏️ **Edit Reminders:**
• "Edit time of [task name] to [new time]"
  Example: "Edit time of take pills to 3pm"
• "Edit name of [task name] to [new name]"
  Example: "Edit name of take pills to take vitamins"

🔔 **When reminders trigger, use the buttons:**
✅ **Complete** - Task finished successfully
❌ **Dismiss** - Skip this reminder
⏰ **Snooze** - Delay by 10 or 30 minutes

Just talk to me like you would a friendly medical assistant! 😊
        """
        await update.message.reply_text(help_msg, parse_mode='Markdown')
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user = update.effective_user
            user_id = user.id
            text = update.message.text.strip()
            
            logger.info(f"💬 User {user_id}: {text}")
            
            # Classify intent
            intent = self.intent_agent.classify_intent(text)
            logger.info(f"🎯 Intent classified as: {intent}")
            
            if intent == 'task_creation':
                await self.handle_task_creation(update, context, text, user_id)
                return
            
            elif intent == 'cancel':
                await self.handle_cancel_request(update, context, text, user_id)
                return
            
            elif intent == 'edit':
                await self.handle_edit_request(update, context, text, user_id)
                return
            
            elif intent == 'status':
                await self.show_pending_tasks(update, context)
                return
            
            elif intent == 'greeting':
                response = f"Hello {user.first_name}! 😊 How can I help you with your health reminders today?"
                await update.message.reply_text(response)
                return
            
            elif intent == 'general_conversation':
                response = await self.conversational_agent.get_response(text, user.first_name)
                await update.message.reply_text(response)
                return
            
        except Exception as e:
            logger.error(f"❌ Error in handle_message: {e}")
            await update.message.reply_text("❌ Sorry, I encountered an error. Please try again.")
    
    async def handle_task_creation(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, user_id: int):
        try:
            tasks = await self.task_extractor.extract_tasks(text)
            
            if tasks:
                responses = []
                scheduled_count = 0
                
                for task_data in tasks:
                    try:
                        # Create task
                        task_id = self.task_manager.create_task(
                            user_id=user_id,
                            task_name=task_data['task'],
                            category=task_data['category'],
                            urgency=task_data['urgency'],
                            scheduled_time=task_data['parsed_time'].isoformat(),
                            local_time_display=task_data['parsed_time'].strftime('%I:%M %p on %B %d, %Y')
                        )
                        
                        # Schedule reminder
                        await self.schedule_reminder(user_id, task_id, task_data, task_data['parsed_time'])
                        
                        responses.append(f"✅ {task_data['task']} - {task_data['parsed_time'].strftime('%I:%M %p on %B %d, %Y')}")
                        scheduled_count += 1
                        
                    except Exception as e:
                        logger.error(f"❌ Error creating task: {e}")
                        responses.append(f"❌ Failed to schedule: {task_data['task']}")
                
                if scheduled_count > 0:
                    response = f"🔔 **Scheduled {scheduled_count} reminder(s):**\n\n" + "\n".join(responses)
                    response += f"\n\n⏰ Current time: {datetime.now(local_tz).strftime('%I:%M %p %Z')}"
                else:
                    response = "❌ Failed to schedule reminders. Please try again with specific times like:\n• '8am' or '8:00am'\n• '13:05' (24-hour format)\n• 'in 30 minutes'\n• '2:30pm'"
            else:
                response = "I couldn't find any reminders to schedule. Try saying something like:\n• 'Remind me to take pills at 8am'\n• 'Remind me to take Adderall at 13:05'\n• 'Set reminder for exercise in 30 minutes'"
            
            await update.message.reply_text(response, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"❌ Error in handle_task_creation: {e}")
            await update.message.reply_text("❌ Error creating reminder. Please try again.")
    
    async def handle_cancel_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, user_id: int):
        try:
            # Extract task name from cancel request
            cancel_patterns = [
                r'cancel\s+(.+?)(?:\s+reminder|\s+task|$)',
                r'delete\s+(.+?)(?:\s+reminder|\s+task|$)',
                r'remove\s+(.+?)(?:\s+reminder|\s+task|$)',
                r'stop\s+(.+?)(?:\s+reminder|\s+task|$)'
            ]
            
            task_name = None
            for pattern in cancel_patterns:
                match = re.search(pattern, text.lower())
                if match:
                    task_name = match.group(1).strip()
                    break
            
            if task_name:
                cancelled_count = self.task_manager.cancel_tasks_by_name(user_id, task_name)
                
                if cancelled_count > 0:
                    # Remove from scheduler
                    pending_tasks = self.task_manager.get_pending_tasks(user_id)
                    for task in pending_tasks:
                        if task_name.lower() in task['task_name'].lower():
                            try:
                                self.scheduler.remove_job(f"reminder_{task['id']}")
                            except:
                                pass
                    
                    response = f"❌ Cancelled: {task_name.title()}\n⏰ Current time: {datetime.now(local_tz).strftime('%I:%M %p %Z')}"
                else:
                    response = f"❌ Could not find a reminder matching '{task_name}'. Use /pending to see your active reminders."
            else:
                response = "Please specify which reminder to cancel. For example:\n• 'Cancel take pills'\n• 'Delete exercise reminder'"
            
            await update.message.reply_text(response)
            
        except Exception as e:
            logger.error(f"❌ Error in handle_cancel_request: {e}")
            await update.message.reply_text("❌ Error cancelling reminder. Please try again.")
    
    async def handle_edit_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, user_id: int):
        try:
            text_lower = text.lower()
            
            # Determine if editing time or name
            is_time_edit = any(phrase in text_lower for phrase in ['edit time', 'change time', 'modify time', 'update time'])
            is_name_edit = any(phrase in text_lower for phrase in ['edit name', 'change name', 'modify name', 'update name', 'rename'])
            
            if not is_time_edit and not is_name_edit:
                await update.message.reply_text(
                    "Please specify what you want to edit:\n"
                    "• 'Edit time of [task name] to [new time]'\n"
                    "• 'Edit name of [task name] to [new name]'"
                )
                return
            
            if is_time_edit:
                # Pattern: "edit time of [task] to [new_time]"
                match = re.search(r'edit\s+time\s+of\s+(.+?)\s+to\s+(.+)', text_lower)
                if not match:
                    await update.message.reply_text(
                        "Please use the format: 'Edit time of [task name] to [new time]'\n"
                        "Example: 'Edit time of take pills to 2pm'"
                    )
                    return
                
                task_name_part = match.group(1).strip()
                new_time_str = match.group(2).strip()
                
                # Find the task
                task = self.task_manager.find_task_by_partial_name(user_id, task_name_part)
                if not task:
                    await update.message.reply_text(f"❌ Could not find a task matching '{task_name_part}'. Please check your pending tasks with /pending")
                    return
                
                # Parse the new time
                new_time = self.task_extractor.parse_time(new_time_str)
                if not new_time:
                    await update.message.reply_text(f"❌ Could not parse the time '{new_time_str}'. Please use formats like '2pm', '14:30', or 'in 30 minutes'")
                    return
                
                # Update the task
                success = self.task_manager.update_task_time(
                    task['id'], 
                    user_id, 
                    new_time.isoformat(),
                    new_time.astimezone(local_tz).strftime('%I:%M %p on %B %d, %Y')
                )
                
                if success:
                    # Remove old scheduler job and add new one
                    try:
                        self.scheduler.remove_job(f"reminder_{task['id']}")
                    except:
                        pass
                    
                    # Schedule new reminder
                    task_data = {
                        'task': task['task_name'],
                        'category': task['category'],
                        'urgency': task['urgency']
                    }
                    await self.schedule_reminder(user_id, task['id'], task_data, new_time)
                    
                    response = f"✅ **Time Updated Successfully!**\n\n📝 **Task:** {task['task_name']}\n🕐 **New Time:** {new_time.strftime('%I:%M %p on %B %d, %Y')}\n\n⏰ Current time: {datetime.now(local_tz).strftime('%I:%M %p %Z')}"
                else:
                    response = "❌ Failed to update the task time. Please try again."
            
            elif is_name_edit:
                # Pattern: "edit name of [task] to [new_name]"
                match = re.search(r'edit\s+name\s+of\s+(.+?)\s+to\s+(.+)', text_lower)
                if not match:
                    match = re.search(r'change\s+name\s+of\s+(.+?)\s+to\s+(.+)', text_lower)
                if not match:
                    match = re.search(r'rename\s+(.+?)\s+to\s+(.+)', text_lower)
                
                if not match:
                    await update.message.reply_text(
                        "Please use the format: 'Edit name of [task name] to [new name]'\n"
                        "Example: 'Edit name of take pills to take vitamins'"
                    )
                    return
                
                task_name_part = match.group(1).strip()
                new_name = match.group(2).strip()
                
                # Find the task
                task = self.task_manager.find_task_by_partial_name(user_id, task_name_part)
                if not task:
                    await update.message.reply_text(f"❌ Could not find a task matching '{task_name_part}'. Please check your pending tasks with /pending")
                    return
                
                # Update the task name
                success = self.task_manager.update_task_name(task['id'], user_id, new_name)
                
                if success:
                    response = f"✅ **Name Updated Successfully!**\n\n📝 **Old Name:** {task['task_name']}\n📝 **New Name:** {new_name}\n🕐 **Scheduled Time:** {task['local_time_display']}\n\n⏰ Current time: {datetime.now(local_tz).strftime('%I:%M %p %Z')}"
                else:
                    response = "❌ Failed to update the task name. Please try again."
            
            await update.message.reply_text(response, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"❌ Error in handle_edit_request: {e}")
            await update.message.reply_text("❌ Error processing edit request. Please try again.")
    
    async def schedule_reminder(self, user_id: int, task_id: str, task_data: Dict[str, Any], scheduled_time: datetime):
        try:
            job_id = f"reminder_{task_id}"
            
            self.scheduler.add_job(
                self.send_reminder,
                trigger=DateTrigger(run_date=scheduled_time),
                args=[user_id, task_id, task_data],
                id=job_id,
                max_instances=1,
                misfire_grace_time=60
            )
            
            logger.info(f"📅 Scheduled reminder for task {task_id} at {scheduled_time}")
        except Exception as e:
            logger.error(f"❌ Error scheduling reminder: {e}")
    
    async def send_reminder(self, user_id: int, task_id: str, task_data: Dict[str, Any]):
        try:
            urgency_emoji = {"Urgent": "🚨", "General": "⏰", "Relaxed": "🔔"}
            category_emoji = {"Medication": "💊", "Exercise": "🏃", "Appointment": "📅", "Other": "📋"}
            
            message = f"""
{urgency_emoji.get(task_data.get('urgency', 'General'), '⏰')} **{task_data.get('urgency', 'General').upper()} REMINDER**

{category_emoji.get(task_data.get('category', 'Other'), '📋')} **{task_data['task']}**

🕐 **Time:** {datetime.now(local_tz).strftime('%I:%M %p')}
📝 **Category:** {task_data.get('category', 'Other')}

**What would you like to do?**
            """
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Complete", callback_data=f"complete_{task_id}"),
                    InlineKeyboardButton("❌ Dismiss", callback_data=f"dismiss_{task_id}")
                ],
                [
                    InlineKeyboardButton("⏰ Snooze 10min", callback_data=f"snooze_10_{task_id}"),
                    InlineKeyboardButton("⏰ Snooze 30min", callback_data=f"snooze_30_{task_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Use the bot application to send message
            # This will be set during initialization
            if hasattr(self, 'application') and self.application:
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                logger.info(f"📢 Sent reminder for task {task_id} to user {user_id}")
            else:
                logger.error("❌ Bot application not available for sending reminder")
            
        except Exception as e:
            logger.error(f"❌ Error sending reminder: {e}")
    
    async def show_pending_tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            pending_tasks = self.task_manager.get_pending_tasks(user_id)
            
            if not pending_tasks:
                await update.message.reply_text("✅ No pending reminders! You're all set. 😊")
                return
            
            response = f"📋 **Your Upcoming Reminders ({len(pending_tasks)}):**\n\n"
            
            for i, task in enumerate(pending_tasks, 1):
                urgency_emoji = {"Urgent": "🚨", "General": "⏰", "Relaxed": "🔔"}
                category_emoji = {"Medication": "💊", "Exercise": "🏃", "Appointment": "📅", "Other": "📋"}
                
                response += f"{i}. {urgency_emoji.get(task['urgency'], '⏰')} **{task['task_name']}**\n"
                response += f"   {category_emoji.get(task['category'], '📋')} {task['local_time_display']}\n\n"
            
            response += f"⏰ Current time: {datetime.now(local_tz).strftime('%I:%M %p %Z')}"
            
            await update.message.reply_text(response, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"❌ Error in show_pending_tasks: {e}")
            await update.message.reply_text("❌ Error retrieving tasks. Please try again.")
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            
            user_id = query.from_user.id
            data = query.data
            
            if data.startswith('complete_'):
                task_id = data.replace('complete_', '')
                success = self.task_manager.complete_task(task_id, user_id)
                
                if success:
                    await query.edit_message_text(
                        "✅ **Task Completed!** Great job! 🎉",
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text("❌ Error marking task as complete.")
            
            elif data.startswith('dismiss_'):
                task_id = data.replace('dismiss_', '')
                success = self.task_manager.dismiss_task(task_id, user_id)
                
                if success:
                    await query.edit_message_text(
                        "❌ **Task Dismissed** - No problem, maybe next time! 😊",
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text("❌ Error dismissing task.")
            
            elif data.startswith('snooze_'):
                parts = data.split('_')
                minutes = int(parts[1])
                task_id = parts[2]
                
                # Get task details for rescheduling
                pending_tasks = self.task_manager.get_pending_tasks(user_id)
                task = next((t for t in pending_tasks if t['id'] == task_id), None)
                
                if task:
                    new_time = datetime.now(local_tz) + timedelta(minutes=minutes)
                    
                    # Update task time
                    success = self.task_manager.update_task_time(
                        task_id, user_id, 
                        new_time.isoformat(),
                        new_time.strftime('%I:%M %p on %B %d, %Y')
                    )
                    
                    if success:
                        # Schedule new reminder
                        task_data = {
                            'task': task['task_name'],
                            'category': task['category'],
                            'urgency': task['urgency']
                        }
                        await self.schedule_reminder(user_id, task_id, task_data, new_time)
                        
                        await query.edit_message_text(
                            f"⏰ **Snoozed for {minutes} minutes**\n"
                            f"Next reminder: {new_time.strftime('%I:%M %p')} 😴",
                            parse_mode='Markdown'
                        )
                    else:
                        await query.edit_message_text("❌ Error snoozing reminder.")
                else:
                    await query.edit_message_text("❌ Task not found.")
            
        except Exception as e:
            logger.error(f"❌ Error in handle_callback: {e}")
            await query.edit_message_text("❌ Error processing action.")

def main():
    # Bot token - replace with your actual token
    BOT_TOKEN = "7794205729:AAHYyh-JdA58vCuEQACgHiLffqtsHMVeeoY"
    
    logger.info("🏥 Initializing Medical Reminder Bot...")
    
    try:
        # Initialize bot
        bot = MedicalReminderBot()
        logger.info("✅ Bot initialized successfully")
        
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Set application reference in bot for sending reminders
        bot.application = application
        
        # Add handlers
        application.add_handler(CommandHandler("start", bot.start_command))
        application.add_handler(CommandHandler("help", bot.help_command))
        application.add_handler(CommandHandler("pending", bot.show_pending_tasks))
        application.add_handler(CommandHandler("status", bot.show_pending_tasks))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
        application.add_handler(CallbackQueryHandler(bot.handle_callback))
        
        logger.info("🚀 Starting Medical Reminder Bot...")
        logger.info(f"⏰ Local timezone: {local_tz}")
        logger.info(f"🌍 UTC time: {datetime.now(utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        logger.info(f"🏠 Local time: {datetime.now(local_tz).strftime('%Y-%m-%d %H:%M:%S %Z')}")
        
        # Start the bot
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
        raise

import time
import httpx

def wait_for_ollama_ready():
    for _ in range(60):
        try:
            response = httpx.post("http://localhost:11434/api/generate", json={
                "model": "mistral:latest",
                "prompt": "ping",
                "stream": False
            }, timeout=10)
            if response.status_code == 200:
                print("✅ Ollama is ready.")
                return
        except Exception as e:
            print(f"Waiting for Ollama to be ready... ({e})")
        time.sleep(2)

if __name__ == "__main__":
    wait_for_ollama_ready()  # <-- Ensures model is loaded before polling
    main()
