import React from 'react';

const DAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

export function DayScheduleRow({ activeDays = [], todayIndex = 0 }) {
  return (
    <div className="schedule-row">
      <div className="schedule-row-label">Weekly Duty</div>
      <div className="days-cells">
        {DAYS.map((letter, idx) => {
          const isActive = activeDays.includes(idx);
          const isToday = idx === todayIndex;
          let cellClass = 'day-cell';
          if (isActive) cellClass += ' active-duty';
          if (isToday) cellClass += ' is-today';

          return (
            <div
              key={idx}
              className={cellClass}
              title={`${['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][idx]}: ${isActive ? 'On Duty' : 'Standby'}${isToday ? ' (Today)' : ''}`}
            >
              {letter}
            </div>
          );
        })}
      </div>
    </div>
  );
}
